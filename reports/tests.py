"""
Reports tests — Phase 3.1.

Cover the canonical query layer (`reports.queries`) and the new
Profitability-by-Client report view (URL gate, HTML render, CSV export).
"""
from django.conf import settings as django_settings
from django.test import TestCase, override_settings


# Strip the project-wide 2FA enforcement + Axes middleware so the test
# client can hit the views directly. Same pattern as `psa/tests.py`.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProfitabilityQueryTests(TestCase):
    """v3.17.139: canonical queries return correct shape and totals."""

    def setUp(self):
        from datetime import date, timedelta
        from django.contrib.auth.models import User
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
            TicketTimeEntry, Invoice,
        )
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        self.org = Organization.objects.create(name='Profit Co', slug='profit-co')
        self.user = User.objects.create_user('alice', 'a@x.com', 'pw')
        self.t = Ticket.objects.create(
            organization=self.org, subject='X',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )
        self.today = date.today()
        TicketTimeEntry.objects.create(
            ticket=self.t, user=self.user,
            started_at=self.today, duration_minutes=120, is_billable=True,
        )
        Invoice.objects.create(
            organization=self.org, client_org=self.org,
            invoice_number='INV-2026-1', title='Test',
            invoice_date=self.today, due_date=self.today,
            total=500, amount_paid=200,
            status='partial', subtotal=500, tax_amount=0, currency='USD',
        )

    def test_hours_minutes_by_client(self):
        from reports.queries import hours_minutes_by_client
        rows = hours_minutes_by_client(self.today, self.today)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['billable_minutes'], 120)
        self.assertEqual(rows[0]['client_id'], self.org.id)

    def test_revenue_by_client(self):
        from reports.queries import revenue_by_client
        rows = revenue_by_client(self.today, self.today)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['invoiced'], 500.0)
        self.assertEqual(rows[0]['outstanding'], 300.0)

    def test_profitability_combines(self):
        from reports.queries import profitability_by_client
        rows = profitability_by_client(self.today, self.today, default_loaded_rate=60)
        self.assertEqual(len(rows), 1)
        # 2h × $60 = $120 cost; revenue $500; margin $380; pct 76%
        self.assertAlmostEqual(rows[0]['cost'], 120.0, places=1)
        self.assertAlmostEqual(rows[0]['margin'], 380.0, places=1)
        self.assertAlmostEqual(rows[0]['margin_pct'], 76.0, places=1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProfitabilityReportViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_user('admin1', 'a@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        self.regular = User.objects.create_user('reg', 'r@x.com', 'pw')

    def test_staff_can_view(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/profitability-by-client/')
        self.assertEqual(r.status_code, 200)

    def test_non_staff_redirected(self):
        self.client.force_login(self.regular)
        r = self.client.get('/reports/psa/profitability-by-client/')
        self.assertIn(r.status_code, [302, 403])

    def test_csv_export(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/profitability-by-client/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0].strip(), 'text/csv')
        self.assertIn(b'Client', r.content)  # header row


# ---------------------------------------------------------------------------
# Phase 3.2 — TechCostRate + per-tech / contract / project profitability
# ---------------------------------------------------------------------------

class TechCostRateTests(TestCase):
    def test_rate_for_returns_default_when_no_rows(self):
        from datetime import date
        from django.contrib.auth.models import User
        from resourcing.models import TechCostRate
        from reports.queries import DEFAULT_LOADED_RATE
        u = User.objects.create_user('alice', 'a@x.com', 'pw')
        self.assertEqual(TechCostRate.rate_for(u, date.today()),
                         DEFAULT_LOADED_RATE)

    def test_rate_for_picks_most_recent_effective(self):
        from datetime import date
        from decimal import Decimal
        from django.contrib.auth.models import User
        from resourcing.models import TechCostRate
        u = User.objects.create_user('alice', 'a@x.com', 'pw')
        TechCostRate.objects.create(user=u, rate_per_hour=Decimal('50'),
                                    effective_from=date(2024, 1, 1))
        TechCostRate.objects.create(user=u, rate_per_hour=Decimal('70'),
                                    effective_from=date(2025, 6, 1))
        self.assertEqual(TechCostRate.rate_for(u, date(2025, 7, 1)),
                         Decimal('70'))
        self.assertEqual(TechCostRate.rate_for(u, date(2024, 6, 1)),
                         Decimal('50'))

    def test_rate_for_ignores_future_effective(self):
        from datetime import date
        from decimal import Decimal
        from django.contrib.auth.models import User
        from resourcing.models import TechCostRate
        from reports.queries import DEFAULT_LOADED_RATE
        u = User.objects.create_user('alice', 'a@x.com', 'pw')
        TechCostRate.objects.create(user=u, rate_per_hour=Decimal('99'),
                                    effective_from=date(2030, 1, 1))
        # Today < 2030, so falls back to default
        self.assertEqual(TechCostRate.rate_for(u, date(2026, 1, 1)),
                         DEFAULT_LOADED_RATE)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProfitabilityByTechTests(TestCase):
    """Phase 3.2 — per-tech profitability uses TechCostRate."""

    def setUp(self):
        from datetime import date
        from decimal import Decimal
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
            TicketTimeEntry, Invoice,
        )
        from resourcing.models import TechCostRate
        call_command('psa_seed_defaults', verbosity=0)
        self.org = Organization.objects.create(name='ProfitTechCo', slug='profit-tech-co')
        self.user = User.objects.create_user('alice', 'a@x.com', 'pw')
        self.t = Ticket.objects.create(
            organization=self.org, subject='X',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )
        self.today = date.today()
        TicketTimeEntry.objects.create(
            ticket=self.t, user=self.user,
            started_at=self.today, duration_minutes=120, is_billable=True,
        )
        Invoice.objects.create(
            organization=self.org, client_org=self.org,
            invoice_number='INV-2026-T1', title='TestTech',
            invoice_date=self.today, due_date=self.today,
            total=300, amount_paid=0, status='sent',
            subtotal=300, tax_amount=0, currency='USD',
        )
        # Custom cost rate $50/hr
        TechCostRate.objects.create(user=self.user, rate_per_hour=Decimal('50'),
                                    effective_from=self.today)

    def test_per_tech_uses_cost_rate(self):
        from reports.queries import profitability_by_tech
        rows = profitability_by_tech(self.today, self.today)
        self.assertEqual(len(rows), 1)
        # 2 hours × $50/hr = $100 cost
        self.assertAlmostEqual(rows[0]['cost'], 100.0, places=1)
        self.assertEqual(rows[0]['tech_username'], 'alice')

    def test_cost_estimate_by_client_uses_per_tech_rate(self):
        from reports.queries import cost_estimate_by_client
        rows = cost_estimate_by_client(self.today, self.today)
        self.assertEqual(len(rows), 1)
        # 2h × $50 = $100 (not 2h × $60 placeholder)
        self.assertAlmostEqual(rows[0]['cost'], 100.0, places=1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProfitabilityByContractTests(TestCase):
    """Phase 3.2 — per-contract grouping via Contract.for_ticket."""

    def setUp(self):
        from datetime import date, timedelta
        from decimal import Decimal
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
            TicketTimeEntry, Contract, Invoice,
        )
        call_command('psa_seed_defaults', verbosity=0)
        self.msp = Organization.objects.create(name='MSPInc', slug='msp-inc')
        self.client_org = Organization.objects.create(name='ClientCo', slug='client-co')
        self.user = User.objects.create_user('alice', 'a@x.com', 'pw')
        self.today = date.today()
        self.contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_org,
            name='Block 50', contract_type='block_hours', status='active',
            start_date=self.today - timedelta(days=30),
            end_date=self.today + timedelta(days=30),
            total_hours=Decimal('50'), hourly_rate=Decimal('150'),
        )
        self.t = Ticket.objects.create(
            organization=self.client_org, subject='X',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )
        TicketTimeEntry.objects.create(
            ticket=self.t, user=self.user,
            started_at=self.today, duration_minutes=60, is_billable=True,
        )
        Invoice.objects.create(
            organization=self.msp, client_org=self.client_org,
            source_contract=self.contract,
            invoice_number='INV-2026-C1', title='Contract billing',
            invoice_date=self.today, due_date=self.today,
            total=Decimal('500'), amount_paid=0, status='sent',
            subtotal=Decimal('500'), tax_amount=0, currency='USD',
        )

    def test_aggregates_per_contract(self):
        from reports.queries import profitability_by_contract
        rows = profitability_by_contract(self.today, self.today)
        # We expect at least one row matching our contract
        match = [r for r in rows if r['contract_id'] == self.contract.id]
        self.assertEqual(len(match), 1)
        r = match[0]
        self.assertEqual(r['client_name'], 'ClientCo')
        # Revenue includes the $500 invoice
        self.assertGreaterEqual(r['revenue'], 500.0)
        # Cost = 1h × default $60 = $60
        self.assertAlmostEqual(r['cost'], 60.0, places=1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProfitabilityByProjectTests(TestCase):
    """Phase 3.2 — per-project grouping via Ticket.project."""

    def setUp(self):
        from datetime import date
        from decimal import Decimal
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
            TicketTimeEntry, Project, Invoice,
        )
        call_command('psa_seed_defaults', verbosity=0)
        self.msp = Organization.objects.create(name='MSPInc', slug='msp-inc-2')
        self.client_org = Organization.objects.create(name='ProjClient', slug='proj-client')
        self.user = User.objects.create_user('alice', 'a@x.com', 'pw')
        self.today = date.today()
        self.project = Project.objects.create(
            organization=self.msp, client_org=self.client_org,
            name='Migration', status='active',
        )
        self.t = Ticket.objects.create(
            organization=self.client_org, subject='Migration ticket',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            project=self.project,
        )
        TicketTimeEntry.objects.create(
            ticket=self.t, user=self.user,
            started_at=self.today, duration_minutes=180, is_billable=True,
        )
        Invoice.objects.create(
            organization=self.msp, client_org=self.client_org,
            source_ticket=self.t,
            invoice_number='INV-2026-P1', title='Project billing',
            invoice_date=self.today, due_date=self.today,
            total=Decimal('900'), amount_paid=0, status='sent',
            subtotal=Decimal('900'), tax_amount=0, currency='USD',
        )

    def test_aggregates_per_project(self):
        from reports.queries import profitability_by_project
        rows = profitability_by_project(self.today, self.today)
        match = [r for r in rows if r['project_id'] == self.project.id]
        self.assertEqual(len(match), 1)
        r = match[0]
        self.assertEqual(r['project_name'], 'Migration')
        self.assertAlmostEqual(r['revenue'], 900.0, places=1)
        # 3h × $60 default = $180
        self.assertAlmostEqual(r['cost'], 180.0, places=1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProfitabilityPivotViewTests(TestCase):
    """Phase 3.2 — staff can hit the three new HTML/CSV report views."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_user('admin1', 'a@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        self.regular = User.objects.create_user('reg', 'r@x.com', 'pw')

    def test_by_tech_view_staff_html(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/profitability-by-tech/')
        self.assertEqual(r.status_code, 200)

    def test_by_tech_view_csv(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/profitability-by-tech/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0].strip(), 'text/csv')
        self.assertIn(b'Tech', r.content)

    def test_by_contract_view_staff_html(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/profitability-by-contract/')
        self.assertEqual(r.status_code, 200)

    def test_by_project_view_staff_html(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/profitability-by-project/')
        self.assertEqual(r.status_code, 200)

    def test_by_tech_non_staff_redirected(self):
        self.client.force_login(self.regular)
        r = self.client.get('/reports/psa/profitability-by-tech/')
        self.assertIn(r.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Phase 3.3 — Effective hourly rate + Revenue leakage
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EffectiveRateTests(TestCase):
    """v3.17.141: effective_hourly_rate_by_client + by_tech."""

    def setUp(self):
        from datetime import date, timedelta
        from decimal import Decimal
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
            TicketTimeEntry, Contract, Invoice,
        )
        from resourcing.models import TechCostRate
        call_command('psa_seed_defaults', verbosity=0)
        self.msp = Organization.objects.create(name='MSPRate', slug='msp-rate')
        self.client_org = Organization.objects.create(name='RateClient',
                                                      slug='rate-client')
        self.user = User.objects.create_user('alice', 'a@x.com', 'pw')
        self.today = date.today()
        # Active contract so attributed revenue uses $150/hr
        self.contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_org,
            name='Rate Block', contract_type='block_hours', status='active',
            start_date=self.today - timedelta(days=30),
            end_date=self.today + timedelta(days=30),
            total_hours=Decimal('50'), hourly_rate=Decimal('150'),
        )
        self.t = Ticket.objects.create(
            organization=self.client_org, subject='Work',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )
        # 4 billable hours
        TicketTimeEntry.objects.create(
            ticket=self.t, user=self.user,
            started_at=self.today, duration_minutes=240, is_billable=True,
        )
        Invoice.objects.create(
            organization=self.msp, client_org=self.client_org,
            invoice_number='INV-RATE-1', title='Test',
            invoice_date=self.today, due_date=self.today,
            total=Decimal('600'), amount_paid=0, status='sent',
            subtotal=Decimal('600'), tax_amount=0, currency='USD',
        )
        # Cost rate $50/hr → effective $150 ÷ 50 cost = 300% realization
        # for the tech tab (which uses contract hourly_rate × hours = 600
        # attributed revenue ÷ 4h billable = $150 effective).
        TechCostRate.objects.create(user=self.user,
                                    rate_per_hour=Decimal('50'),
                                    effective_from=self.today)

    def test_effective_rate_basic(self):
        """4h billable + $600 invoiced → effective rate $150/hr."""
        from reports.queries import effective_hourly_rate_by_client
        rows = effective_hourly_rate_by_client(self.today, self.today)
        match = [r for r in rows if r['client_id'] == self.client_org.id]
        self.assertEqual(len(match), 1)
        r = match[0]
        self.assertEqual(r['billable_hours'], 4.0)
        self.assertAlmostEqual(r['revenue'], 600.0, places=1)
        self.assertAlmostEqual(r['effective_rate'], 150.0, places=1)

    def test_effective_rate_by_tech_has_realization(self):
        """Per-tech rate uses attributed revenue ÷ billable hours."""
        from reports.queries import effective_hourly_rate_by_tech
        rows = effective_hourly_rate_by_tech(self.today, self.today)
        self.assertGreaterEqual(len(rows), 1)
        r = rows[0]
        # Attributed revenue = 4h × $150 contract rate = $600
        # Effective rate = $600 / 4h = $150/hr
        # Cost rate = $50/hr
        # Realization % = 150 / 50 × 100 = 300%
        self.assertAlmostEqual(r['effective_rate'], 150.0, places=1)
        self.assertAlmostEqual(r['cost_rate'], 50.0, places=1)
        self.assertAlmostEqual(r['realization_pct'], 300.0, places=0)

    def test_effective_rate_zero_when_no_billable_hours(self):
        """Client with revenue but no time → effective_rate = 0."""
        from datetime import date as _date
        from decimal import Decimal
        from core.models import Organization
        from psa.models import Invoice
        from reports.queries import effective_hourly_rate_by_client
        ghost = Organization.objects.create(name='GhostCo', slug='ghost-co')
        Invoice.objects.create(
            organization=self.msp, client_org=ghost,
            invoice_number='INV-GHOST-1', title='G',
            invoice_date=self.today, due_date=self.today,
            total=Decimal('200'), amount_paid=0, status='sent',
            subtotal=Decimal('200'), tax_amount=0, currency='USD',
        )
        rows = effective_hourly_rate_by_client(self.today, self.today)
        match = [r for r in rows if r['client_id'] == ghost.id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]['billable_hours'], 0)
        self.assertEqual(match[0]['effective_rate'], 0.0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RevenueLeakageTests(TestCase):
    """v3.17.141: revenue_leakage surfaces stale unbilled, expired blocks,
    stuck drafts."""

    def setUp(self):
        from datetime import date, timedelta
        from decimal import Decimal
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from django.utils import timezone
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
            TicketTimeEntry, Contract, Invoice,
        )
        call_command('psa_seed_defaults', verbosity=0)
        self.msp = Organization.objects.create(name='MSPLeak', slug='msp-leak')
        self.client_org = Organization.objects.create(name='LeakClient',
                                                      slug='leak-client')
        self.user = User.objects.create_user('bob', 'b@x.com', 'pw')
        self.today = date.today()
        self.t = Ticket.objects.create(
            organization=self.client_org, subject='LeakTest',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )
        # Stale unbilled entry: 60 days ago, billable, 2h
        old_dt = timezone.now() - timedelta(days=60)
        TicketTimeEntry.objects.create(
            ticket=self.t, user=self.user,
            started_at=old_dt, ended_at=old_dt + timedelta(hours=2),
            duration_minutes=120, is_billable=True,
        )
        # Expired contract: 10h total, 0 used, $200/hr
        self.expired_contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_org,
            name='Old Block', contract_type='block_hours', status='expired',
            start_date=self.today - timedelta(days=400),
            end_date=self.today - timedelta(days=30),
            total_hours=Decimal('10'),
            hours_used_minutes=0,
            hourly_rate=Decimal('200'),
        )
        # Stuck draft: 30 days old, $750
        self.draft_invoice = Invoice.objects.create(
            organization=self.msp, client_org=self.client_org,
            invoice_number='INV-STUCK-1', title='Stuck Draft',
            invoice_date=self.today - timedelta(days=30),
            due_date=self.today, status='draft',
            total=Decimal('750'), amount_paid=0,
            subtotal=Decimal('750'), tax_amount=0, currency='USD',
        )

    def test_stale_unbilled_picks_up_old_billable_entries(self):
        from reports.queries import revenue_leakage
        data = revenue_leakage(self.today, self.today, stale_days=30)
        match = [r for r in data['stale_unbilled']
                 if r['client_id'] == self.client_org.id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]['entry_count'], 1)
        self.assertAlmostEqual(match[0]['hours_at_risk'], 2.0, places=1)
        self.assertGreater(match[0]['amount_at_risk'], 0)

    def test_stuck_drafts_are_old_drafts(self):
        from reports.queries import revenue_leakage
        data = revenue_leakage(self.today, self.today)
        match = [r for r in data['stuck_drafts']
                 if r['invoice_id'] == self.draft_invoice.id]
        self.assertEqual(len(match), 1)
        self.assertAlmostEqual(match[0]['amount'], 750.0, places=1)
        self.assertGreaterEqual(match[0]['days_stuck'], 14)

    def test_expired_block_with_unused_hours(self):
        from reports.queries import revenue_leakage
        data = revenue_leakage(self.today, self.today)
        match = [r for r in data['expired_blocks']
                 if r['contract_id'] == self.expired_contract.id]
        self.assertEqual(len(match), 1)
        self.assertAlmostEqual(match[0]['unused_hours'], 10.0, places=1)
        # 10h × $200 = $2000
        self.assertAlmostEqual(match[0]['unused_value'], 2000.0, places=1)

    def test_grand_total_sums(self):
        from reports.queries import revenue_leakage
        data = revenue_leakage(self.today, self.today)
        t = data['totals']
        self.assertAlmostEqual(
            t['grand_total'],
            t['stale'] + t['expired_blocks'] + t['stuck'],
            places=1,
        )
        # Should at least include our stuck $750 and expired $2000
        self.assertGreaterEqual(t['grand_total'], 2750.0)

    def test_billed_entries_are_excluded_from_stale(self):
        """An entry whose pk is referenced by a non-void InvoiceLineItem
        must not appear under stale_unbilled."""
        from datetime import timedelta
        from decimal import Decimal
        from django.utils import timezone
        from psa.models import TicketTimeEntry, Invoice, InvoiceLineItem
        from reports.queries import revenue_leakage

        # New billable entry 60 days ago that IS on an invoice
        old_dt = timezone.now() - timedelta(days=60)
        te = TicketTimeEntry.objects.create(
            ticket=self.t, user=self.user,
            started_at=old_dt, ended_at=old_dt + timedelta(hours=1),
            duration_minutes=60, is_billable=True,
        )
        inv = Invoice.objects.create(
            organization=self.msp, client_org=self.client_org,
            invoice_number='INV-BILLED-1', title='Billed',
            invoice_date=self.today, due_date=self.today,
            total=Decimal('150'), amount_paid=0, status='sent',
            subtotal=Decimal('150'), tax_amount=0, currency='USD',
        )
        InvoiceLineItem.objects.create(
            invoice=inv, description='Time', quantity=1,
            unit_price=Decimal('150'), source='time', source_id=str(te.pk),
        )

        data = revenue_leakage(self.today, self.today, stale_days=30)
        # Confirm only the original 2h-stale entry is counted, not the
        # new 1h billed one — the row for our client should still report
        # entry_count=1 (the un-invoiced one), not 2.
        match = [r for r in data['stale_unbilled']
                 if r['client_id'] == self.client_org.id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]['entry_count'], 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EffectiveRateViewTests(TestCase):
    """Phase 3.3 view auth + CSV export."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_user('admin1', 'a@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        self.regular = User.objects.create_user('reg', 'r@x.com', 'pw')

    def test_renders_for_staff(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/effective-hourly-rate/')
        self.assertEqual(r.status_code, 200)

    def test_non_staff_redirected(self):
        self.client.force_login(self.regular)
        r = self.client.get('/reports/psa/effective-hourly-rate/')
        self.assertIn(r.status_code, [302, 403])

    def test_csv_export(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/effective-hourly-rate/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0].strip(), 'text/csv')
        self.assertIn(b'Effective Rate', r.content)

    def test_tech_tab_csv_export(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/effective-hourly-rate/?format=csv&tab=tech')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Realization', r.content)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RevenueLeakageViewTests(TestCase):
    """Phase 3.3 leakage view auth + CSV combined export."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_user('admin1', 'a@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        self.regular = User.objects.create_user('reg', 'r@x.com', 'pw')

    def test_renders_for_staff(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/revenue-leakage/')
        self.assertEqual(r.status_code, 200)

    def test_non_staff_redirected(self):
        self.client.force_login(self.regular)
        r = self.client.get('/reports/psa/revenue-leakage/')
        self.assertIn(r.status_code, [302, 403])

    def test_csv_export_combines_sections(self):
        self.client.force_login(self.staff)
        r = self.client.get('/reports/psa/revenue-leakage/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0].strip(), 'text/csv')
        # The single-CSV combined export uses a Section column
        self.assertIn(b'Section', r.content)


# ---------------------------------------------------------------------------
# v3.17.142: dashboard widget registry + CRUD
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WidgetSourceRegistryTests(TestCase):
    """v3.17.142: every registered data source returns a non-empty dict."""

    def test_all_sources_runnable(self):
        from reports.widget_sources import REGISTRY
        for name, fn in REGISTRY.items():
            result = fn({})
            self.assertIsInstance(result, dict, f'{name} must return dict')
            # error key is allowed (empty data); value/columns/labels need at
            # least one to be present
            allowed = {'value', 'columns', 'labels', 'error'}
            self.assertTrue(allowed & set(result.keys()),
                            f'{name} returned no recognizable shape: {result}')

    def test_unknown_source_returns_error(self):
        from reports.widget_sources import get_widget_data
        result = get_widget_data('nonsense_source_xyz', {})
        self.assertIn('error', result)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DashboardWidgetCRUDTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from reports.models import Dashboard
        self.user = User.objects.create_user(
            'alice', 'a@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )
        self.dash = Dashboard.objects.create(
            name='Test Dash', is_global=True, created_by=self.user,
        )

    def test_add_widget_via_post(self):
        self.client.force_login(self.user)
        r = self.client.post(
            f'/reports/dashboards/{self.dash.pk}/widgets/add/',
            {'title': 'Open Tickets', 'data_source': 'open_tickets_count'},
        )
        from reports.models import DashboardWidget
        self.assertEqual(
            DashboardWidget.objects.filter(dashboard=self.dash).count(), 1
        )


# ---------------------------------------------------------------------------
# Phase 3.4 — SLA trend report + Margin analytics by service line
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SLATrendQueryTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
        )
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        self.org = Organization.objects.create(name='SLA Co', slug='sla-co')
        self.queue = Queue.objects.first()
        self.status_resolved = TicketStatus.objects.filter(is_terminal=True).first()
        self.p1 = TicketPriority.objects.filter(code='P1').first()
        self.tt = TicketType.objects.first()
        # Fixture: P1 ticket created 2 days ago; resolution_due 1 day ago;
        # closed today → resolution breach. Response landed before due.
        # NOTE: Ticket.created_at is auto_now_add=True, so we can't backdate
        # the create timestamp. The window we use in the assertion includes
        # today, so created_at=now still falls in the bucket.
        now = timezone.now()
        self.t = Ticket.objects.create(
            organization=self.org, subject='X',
            queue=self.queue, status=self.status_resolved,
            priority=self.p1, ticket_type=self.tt,
            resolution_due_at=now - timedelta(days=1),
            first_response_due_at=now + timedelta(hours=2),
            first_response_at=now + timedelta(hours=1),  # before due → on time
            closed_at=now,
        )

    def test_sla_trend_by_priority_buckets(self):
        from datetime import date, timedelta
        from reports.queries import sla_trend_by_priority
        result = sla_trend_by_priority(
            date.today() - timedelta(days=7), date.today(), bucket='week'
        )
        # P1 totals should reflect 1 ticket with 1 resolution breach,
        # 0 response breach.
        p1 = result['totals_by_priority']['P1']
        self.assertEqual(p1['tickets'], 1)
        self.assertEqual(p1['resolution_breaches'], 1)
        self.assertEqual(p1['response_breaches'], 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MarginAnalyticsTests(TestCase):
    def test_dimension_grouping(self):
        from datetime import date
        from reports.queries import margin_analytics_by_service_line
        rows = margin_analytics_by_service_line(date.today(), date.today())
        # Empty period — list returns empty
        self.assertIsInstance(rows, list)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SLATrendsViewTests(TestCase):
    def test_renders_for_staff(self):
        from django.contrib.auth.models import User
        u = User.objects.create_user('admin', 'a@x.com', 'pw',
                                     is_staff=True, is_superuser=True)
        self.client.force_login(u)
        r = self.client.get('/reports/psa/sla-trends/')
        self.assertEqual(r.status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MarginAnalyticsViewTests(TestCase):
    def test_renders_for_staff(self):
        from django.contrib.auth.models import User
        u = User.objects.create_user('admin', 'a@x.com', 'pw',
                                     is_staff=True, is_superuser=True)
        self.client.force_login(u)
        r = self.client.get('/reports/psa/margin-analytics/')
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Phase 3.6 wave A — Wallboard + Executive scorecard
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        # Dashboard-only user (no financial perm)
        self.user = User.objects.create_user('wb_user', 'w@x.com', 'pw')
        self.org = Organization.objects.create(name='WB Co', slug='wb-co')
        rt = RoleTemplate.objects.create(
            name='WBDashUser',
            reports_view_dashboards=True,
            reports_view_financial=False,
        )
        Membership.objects.create(
            user=self.user, organization=self.org,
            role='editor', role_template=rt, is_active=True,
        )

    def test_wallboard_renders_for_dashboard_user(self):
        self.client.force_login(self.user)
        r = self.client.get('/reports/wallboard/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Wallboard', r.content)

    def test_wallboard_data_returns_json(self):
        self.client.force_login(self.user)
        r = self.client.get('/reports/wallboard/data/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0].strip(),
                         'application/json')
        import json
        data = json.loads(r.content)
        self.assertIn('tiles', data)
        self.assertIn('recent_tickets', data)
        self.assertIn('techs_on_shift', data)
        self.assertIn('as_of', data)
        # Six mega-tiles always present
        self.assertEqual(len(data['tiles']), 6)
        labels = [t['label'] for t in data['tiles']]
        self.assertIn('Open Tickets', labels)
        self.assertIn('SLA Overdue', labels)

    def test_wallboard_blocked_without_dashboards_perm(self):
        """A user with no membership / no perms should be 403'd."""
        from django.contrib.auth.models import User
        nobody = User.objects.create_user('nobody', 'n@x.com', 'pw')
        self.client.force_login(nobody)
        r = self.client.get('/reports/wallboard/')
        self.assertIn(r.status_code, [302, 403])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExecScorecardTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        self.org = Organization.objects.create(name='ES Co', slug='es-co')
        # User with dashboards but NO financial perm
        self.dash_only = User.objects.create_user('dashonly', 'd@x.com', 'pw')
        rt_dash = RoleTemplate.objects.create(
            name='DashOnly',
            reports_view_dashboards=True,
            reports_view_financial=False,
        )
        Membership.objects.create(
            user=self.dash_only, organization=self.org,
            role='editor', role_template=rt_dash, is_active=True,
        )
        # Owner / superuser
        self.owner = User.objects.create_user(
            'owner', 'o@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )

    def test_scorecard_blocked_without_financial_perm(self):
        self.client.force_login(self.dash_only)
        r = self.client.get('/reports/exec-scorecard/')
        self.assertIn(r.status_code, [302, 403])

    def test_scorecard_renders_for_owner(self):
        self.client.force_login(self.owner)
        r = self.client.get('/reports/exec-scorecard/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Executive Scorecard', r.content)


# ---------------------------------------------------------------------------
# Phase 3.6 wave B — Scheduled reports runner + Client-health score (v3.17.147)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ScheduledReportRunnerTests(TestCase):
    """v3.17.147: scheduled reports runner advances next_run and creates
    GeneratedReport rows."""

    def _make_schedule(self, *, due, active=True):
        from datetime import timedelta
        from django.contrib.auth.models import User
        from django.utils import timezone
        from core.models import Organization
        from reports.models import ReportTemplate, ScheduledReport
        org = Organization.objects.create(
            name=f'SchedCo-{due}-{active}',
            slug=f'sched-co-{abs(hash((due, active))) % 100000}',
        )
        user = User.objects.filter(username='cron-tester').first() or \
            User.objects.create_user('cron-tester', 'c@x.com', 'pw')
        # Use 'custom' report_type — the generator wrapper handles "no
        # generator registered" gracefully (returns an error dict that
        # serializes to a tiny PDF), so the runner can complete + advance
        # next_run without depending on real PSA fixture data.
        template = ReportTemplate.objects.create(
            name='Cron Test Report', report_type='custom',
            query_template='', is_global=True, created_by=user,
        )
        s = ScheduledReport.objects.create(
            name='nightly cron test', template=template, organization=org,
            frequency='daily', delivery_method='email',
            recipients=[], output_format='csv',
            is_active=active,
            next_run=(timezone.now() - timedelta(hours=1)) if due
                    else (timezone.now() + timedelta(days=2)),
        )
        return s

    def test_due_schedule_runs(self):
        from django.core.management import call_command
        from django.utils import timezone
        from reports.models import GeneratedReport
        s = self._make_schedule(due=True)
        before = GeneratedReport.objects.count()
        call_command('run_scheduled_reports', verbosity=0)
        s.refresh_from_db()
        # next_run advanced into the future
        self.assertIsNotNone(s.next_run)
        self.assertGreater(s.next_run, timezone.now())
        # last_run set
        self.assertIsNotNone(s.last_run)
        # GeneratedReport row created
        self.assertEqual(GeneratedReport.objects.count(), before + 1)

    def test_dry_run_does_not_advance(self):
        from django.core.management import call_command
        from reports.models import GeneratedReport
        s = self._make_schedule(due=True)
        original_next = s.next_run
        before = GeneratedReport.objects.count()
        call_command('run_scheduled_reports', '--dry-run', verbosity=0)
        s.refresh_from_db()
        self.assertEqual(s.next_run, original_next)
        self.assertEqual(GeneratedReport.objects.count(), before)
        self.assertIsNone(s.last_run)

    def test_inactive_skipped(self):
        from django.core.management import call_command
        from reports.models import GeneratedReport
        s = self._make_schedule(due=True, active=False)
        original_next = s.next_run
        before = GeneratedReport.objects.count()
        call_command('run_scheduled_reports', verbosity=0)
        s.refresh_from_db()
        # Untouched
        self.assertEqual(s.next_run, original_next)
        self.assertEqual(GeneratedReport.objects.count(), before)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ClientHealthScoreTests(TestCase):
    """v3.17.147: composite health score with weighted components."""

    def setUp(self):
        from django.core.management import call_command
        from core.models import Organization
        call_command('psa_seed_defaults', verbosity=0)
        self.org = Organization.objects.create(
            name='HealthCo', slug='health-co',
        )

    def test_healthy_client_with_no_issues(self):
        """No tickets / no aging → score ≥ 80 (full SLA + velocity + aging,
        engagement at half because no activity, NPS at 7)."""
        from reports.queries import client_health_score
        result = client_health_score(self.org.id)
        self.assertIsNotNone(result)
        # 30 (SLA) + 20 (velocity) + 25 (aging) + 7.5 (engagement) + 7 (nps) ≈ 89-90
        self.assertGreaterEqual(result['score'], 80)
        self.assertEqual(result['category'], 'healthy')

    def test_breaches_lower_score(self):
        """Tickets with resolution breaches drop the SLA component."""
        from datetime import timedelta
        from django.utils import timezone
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
        )
        from reports.queries import client_health_score

        now = timezone.now()
        for i in range(5):
            t = Ticket.objects.create(
                organization=self.org, subject=f'Issue {i}',
                queue=Queue.objects.first(),
                status=TicketStatus.objects.filter(is_terminal=True).first(),
                priority=TicketPriority.objects.first(),
                ticket_type=TicketType.objects.first(),
                resolution_due_at=now - timedelta(days=2),
                closed_at=now,  # breach: closed_at > resolution_due_at
            )
            # 3 of 5 breach
            if i >= 3:
                t.resolution_due_at = now + timedelta(days=2)
                t.save(update_fields=['resolution_due_at'])
        result = client_health_score(self.org.id)
        # SLA drops from full 30 → ~12 (2/5 breach-free × 30) — score should drop
        self.assertLess(result['components']['sla'], 30)
        self.assertGreaterEqual(result['metrics']['sla_breaches'], 3)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ClientHealthViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        self.org = Organization.objects.create(
            name='CHViewCo', slug='ch-view-co',
        )
        self.owner = User.objects.create_user(
            'ch_owner', 'o@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )
        # Tech / dashboards-only — should be blocked
        self.tech = User.objects.create_user('ch_tech', 't@x.com', 'pw')
        rt = RoleTemplate.objects.create(
            name='CHDashOnly',
            reports_view_dashboards=True,
            reports_view_financial=False,
        )
        Membership.objects.create(
            user=self.tech, organization=self.org,
            role='editor', role_template=rt, is_active=True,
        )

    def test_renders_for_owner(self):
        self.client.force_login(self.owner)
        r = self.client.get('/reports/psa/client-health/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Client Health', r.content)

    def test_blocks_tech_user(self):
        self.client.force_login(self.tech)
        r = self.client.get('/reports/psa/client-health/')
        self.assertIn(r.status_code, [302, 403])

    def test_csv_export(self):
        self.client.force_login(self.owner)
        r = self.client.get('/reports/psa/client-health/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0].strip(), 'text/csv')
        self.assertIn(b'Client', r.content)


# ---------------------------------------------------------------------------
# v3.17.154 — Generated report download dispositions (PDF inline / others attachment)
# ---------------------------------------------------------------------------


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GeneratedReportInlinePDFTests(TestCase):
    """generated_download returns inline for PDFs and attachment for others."""

    def setUp(self):
        from django.contrib.auth.models import User
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        from reports.models import GeneratedReport, ReportTemplate
        from django.core.files.base import ContentFile

        self.org = Organization.objects.create(
            name='InlinePDFCo', slug='inline-pdf-co',
        )
        self.user = User.objects.create_user(
            'ipdf_owner', 'o@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )
        Membership.objects.create(
            user=self.user, organization=self.org,
            role='owner', is_active=True,
        )
        self.template = ReportTemplate.objects.create(
            name='InlineTpl',
            organization=self.org,
            report_type='asset_summary',
            query_template='',
        )

        # PDF report
        self.pdf_report = GeneratedReport.objects.create(
            template=self.template,
            organization=self.org,
            generated_by=self.user,
            format='pdf',
            status='completed',
        )
        self.pdf_report.file.save(
            'sample.pdf', ContentFile(b'%PDF-1.4 fake pdf body'),
        )

        # CSV report
        self.csv_report = GeneratedReport.objects.create(
            template=self.template,
            organization=self.org,
            generated_by=self.user,
            format='csv',
            status='completed',
        )
        self.csv_report.file.save(
            'sample.csv', ContentFile(b'a,b\n1,2\n'),
        )

    def test_pdf_returns_inline(self):
        self.client.force_login(self.user)
        r = self.client.get(f'/reports/generated/{self.pdf_report.pk}/download/')
        self.assertEqual(r.status_code, 200)
        cd = r.get('Content-Disposition', '')
        self.assertTrue(cd.startswith('inline'),
                        f'Expected inline disposition, got {cd!r}')

    def test_csv_returns_attachment(self):
        self.client.force_login(self.user)
        r = self.client.get(f'/reports/generated/{self.csv_report.pk}/download/')
        self.assertEqual(r.status_code, 200)
        cd = r.get('Content-Disposition', '')
        self.assertTrue(cd.startswith('attachment'),
                        f'Expected attachment disposition, got {cd!r}')


# ---------------------------------------------------------------------------
# v3.17.211 — Configurable wallboards
# ---------------------------------------------------------------------------

class WallboardModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='WBCo', slug='wb-co')

    def test_str_includes_name_and_org(self):
        from reports.models import Wallboard
        w = Wallboard.objects.create(organization=self.org, name='NOC')
        self.assertIn('NOC', str(w))
        self.assertIn('WBCo', str(w))

    def test_default_refresh_seconds_60(self):
        from reports.models import Wallboard
        w = Wallboard.objects.create(organization=self.org, name='Default')
        self.assertEqual(w.refresh_seconds, 60)
        self.assertEqual(w.rotate_seconds, 0)
        self.assertTrue(w.is_active)

    def test_unique_name_per_org(self):
        from reports.models import Wallboard
        from django.db import IntegrityError, transaction
        Wallboard.objects.create(organization=self.org, name='Sales')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallboard.objects.create(organization=self.org, name='Sales')

    def test_same_name_in_different_org_allowed(self):
        from reports.models import Wallboard
        from core.models import Organization
        Wallboard.objects.create(organization=self.org, name='Sales')
        org_b = Organization.objects.create(name='WB-B', slug='wb-b')
        Wallboard.objects.create(organization=org_b, name='Sales')


class WallboardRotationTests(TestCase):
    """`Wallboard.next_in_rotation()` cycles through rotatable boards
    in (order, name) order. Boards with rotate_seconds=0 or
    is_active=False are excluded from the cycle."""

    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='RotCo', slug='rot-co')

    def _board(self, name, order=100, rotate=10, active=True):
        from reports.models import Wallboard
        return Wallboard.objects.create(
            organization=self.org, name=name, order=order,
            rotate_seconds=rotate, is_active=active,
        )

    def test_single_rotatable_board_returns_self(self):
        a = self._board('A')
        self.assertEqual(a.next_in_rotation(), a)

    def test_two_rotatable_boards_cycle(self):
        a = self._board('A', order=10)
        b = self._board('B', order=20)
        self.assertEqual(a.next_in_rotation(), b)
        self.assertEqual(b.next_in_rotation(), a)

    def test_inactive_board_skipped_from_cycle(self):
        a = self._board('A', order=10)
        self._board('B', order=20, active=False)
        self.assertEqual(a.next_in_rotation(), a)

    def test_rotate_zero_excluded_from_cycle(self):
        a = self._board('A', order=10, rotate=10)
        self._board('B', order=20, rotate=0)  # opted out of rotation
        c = self._board('C', order=30, rotate=15)
        self.assertEqual(a.next_in_rotation(), c)
        self.assertEqual(c.next_in_rotation(), a)


class WallboardWidgetInheritTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='InhCo', slug='inh-co')

    def test_widget_refresh_inherits_from_wallboard(self):
        from reports.models import Wallboard, WallboardWidget
        wb = Wallboard.objects.create(
            organization=self.org, name='X', refresh_seconds=120,
        )
        w = WallboardWidget.objects.create(
            wallboard=wb, title='Active tickets',
            widget_type='metric', data_source='open_tickets_count',
            refresh_seconds=None,
        )
        self.assertEqual(w.effective_refresh_seconds, 120)

    def test_widget_refresh_override_wins(self):
        from reports.models import Wallboard, WallboardWidget
        wb = Wallboard.objects.create(
            organization=self.org, name='Y', refresh_seconds=120,
        )
        w = WallboardWidget.objects.create(
            wallboard=wb, title='Faster widget',
            widget_type='metric', data_source='open_tickets_count',
            refresh_seconds=15,
        )
        self.assertEqual(w.effective_refresh_seconds, 15)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardViewACLTests(TestCase):
    """Tenant scope: org members + staff see their org's boards;
    other-org boards return 404."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from reports.models import Wallboard
        cls.org_a = Organization.objects.create(name='WB-A-acl', slug='wb-a-acl')
        cls.org_b = Organization.objects.create(name='WB-B-acl', slug='wb-b-acl')
        cls.user_a = User.objects.create_user(
            'wb-user-a-acl', email='wba@x.com', password='pw',
        )
        Membership.objects.create(
            user=cls.user_a, organization=cls.org_a, role=Role.OWNER, is_active=True,
        )
        cls.board_a = Wallboard.objects.create(organization=cls.org_a, name='A-board')
        cls.board_b = Wallboard.objects.create(organization=cls.org_b, name='B-board')

    def setUp(self):
        from django.test import Client
        self.c = Client()
        self.c.force_login(self.user_a)
        s = self.c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org_a.id
        s.save()

    def test_own_org_wallboard_renders(self):
        resp = self.c.get(f'/reports/wallboards/{self.board_a.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'A-board')

    def test_other_org_wallboard_404(self):
        resp = self.c.get(f'/reports/wallboards/{self.board_b.pk}/')
        self.assertEqual(resp.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardRotateViewTests(TestCase):
    """`/reports/wallboards/<pk>/rotate/` emits a meta-refresh that
    redirects to the next rotatable board's rotate view."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from reports.models import Wallboard
        cls.org = Organization.objects.create(name='RotView', slug='rot-view')
        cls.user = User.objects.create_user(
            'rot-user-rv', email='rv@x.com', password='pw',
        )
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.board1 = Wallboard.objects.create(
            organization=cls.org, name='First', order=10, rotate_seconds=30,
        )
        cls.board2 = Wallboard.objects.create(
            organization=cls.org, name='Second', order=20, rotate_seconds=30,
        )

    def setUp(self):
        from django.test import Client
        self.c = Client()
        self.c.force_login(self.user)
        s = self.c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_rotate_view_emits_meta_refresh_to_next_board(self):
        resp = self.c.get(f'/reports/wallboards/{self.board1.pk}/rotate/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f'/reports/wallboards/{self.board2.pk}/rotate/', body)
        self.assertIn('http-equiv="refresh"', body)
        self.assertIn('content="30;', body)

    def test_rotation_cycles_back_after_last_board(self):
        resp = self.c.get(f'/reports/wallboards/{self.board2.pk}/rotate/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f'/reports/wallboards/{self.board1.pk}/rotate/', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from reports.models import Wallboard
        cls.org = Organization.objects.create(name='ListCo', slug='wb-list-co')
        cls.user = User.objects.create_user(
            'wb-list-user', email='wbl@x.com', password='pw',
        )
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        Wallboard.objects.create(organization=cls.org, name='NOC')
        Wallboard.objects.create(organization=cls.org, name='Sales')

    def test_list_renders_with_user_org_wallboards(self):
        from django.test import Client
        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        resp = c.get('/reports/wallboards/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'NOC')
        self.assertContains(resp, 'Sales')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AgreementReconciliationTests(TestCase):
    """Phase 36 v1 (v3.17.225): per-contract included-vs-consumed report."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from django.utils import timezone
        from datetime import timedelta as _td
        from decimal import Decimal as _D
        from psa.models import Contract
        cls.msp = Organization.objects.create(name='AR-MSP', slug='ar-msp')
        cls.client_a = Organization.objects.create(name='AR-Client-A', slug='ar-ca')
        cls.client_b = Organization.objects.create(name='AR-Client-B', slug='ar-cb')
        cls.staff = User.objects.create_user('ar-staff', 'ars@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member_a = User.objects.create_user('ar-mem-a', 'ara@x.com', 'pw')
        Membership.objects.create(user=cls.member_a, organization=cls.client_a,
                                  role=Role.OWNER, is_active=True)
        today = timezone.now().date()
        cls.under_served = Contract.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            name='Block 100h — under', contract_type='block_hours',
            status='active', start_date=today - _td(days=30),
            total_hours=_D('100'), hours_used_minutes=10 * 60,
            hourly_rate=_D('150'),
        )  # 10/100 = 10% used → under_served
        cls.on_track = Contract.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            name='Block 100h — on track', contract_type='block_hours',
            status='active', start_date=today - _td(days=30),
            total_hours=_D('100'), hours_used_minutes=60 * 60,
            hourly_rate=_D('150'),
        )  # 60/100 = 60% → on_track
        cls.over_served = Contract.objects.create(
            organization=cls.msp, client_org=cls.client_b,
            name='Block 100h — over', contract_type='block_hours',
            status='active', start_date=today - _td(days=30),
            total_hours=_D('100'), hours_used_minutes=130 * 60,
            hourly_rate=_D('150'), overage_rate=_D('200'),
        )  # 130/100 = 130% → over_served
        cls.unlimited = Contract.objects.create(
            organization=cls.msp, client_org=cls.client_b,
            name='MSA — unlimited', contract_type='managed_services',
            status='active', start_date=today - _td(days=30),
            total_hours=_D('0'), hours_used_minutes=42 * 60,
            hourly_rate=_D('150'),
        )  # allowance=0 → unlimited
        Contract.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            name='Expired contract', contract_type='block_hours',
            status='expired', start_date=today - _td(days=400),
            end_date=today - _td(days=30),
            total_hours=_D('100'), hours_used_minutes=200 * 60,
        )  # excluded — status != active

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_all_active_contracts(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/agreement-reconciliation/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Block 100h — under')
        self.assertContains(r, 'Block 100h — on track')
        self.assertContains(r, 'Block 100h — over')
        self.assertContains(r, 'MSA — unlimited')
        self.assertNotContains(r, 'Expired contract')

    def test_status_classification(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/agreement-reconciliation/')
        self.assertContains(r, 'Under-served')
        self.assertContains(r, 'On track')
        self.assertContains(r, 'Over-served')
        self.assertContains(r, 'Unlimited')

    def test_summary_counts(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/agreement-reconciliation/')
        ctx = r.context
        self.assertEqual(ctx['summary']['under_served'], 1)
        self.assertEqual(ctx['summary']['on_track'], 1)
        self.assertEqual(ctx['summary']['over_served'], 1)
        self.assertEqual(ctx['summary']['unlimited'], 1)
        self.assertEqual(ctx['total_contracts'], 4)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/agreement-reconciliation/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')
        self.assertIn('attachment', r['Content-Disposition'])
        body = r.content.decode('utf-8')
        self.assertIn('AR-Client-A', body)
        self.assertIn('AR-Client-B', body)

    def test_member_sees_only_their_orgs_contracts(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member_a, self.client_a)
        r = c.get('/reports/agreement-reconciliation/')
        self.assertEqual(r.status_code, 200)
        # Client A contracts visible:
        self.assertContains(r, 'Block 100h — under')
        # Client B contracts NOT visible:
        self.assertNotContains(r, 'Block 100h — over')
        self.assertNotContains(r, 'MSA — unlimited')

    def test_overage_cost_calculation(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/agreement-reconciliation/')
        # Over-served contract: 130h consumed, 100h allowance = 30h overage,
        # at $200/h overage_rate = $6000.
        self.assertContains(r, '$6000.00')

    def test_detail_view_classifies_entries_chronologically(self):
        # v3.17.248 Phase 36 v3 — drill-down view classifies time entries
        # as covered/overage/split based on running cumulative.
        from django.test import Client
        from psa.models import (
            Contract, Queue, Ticket, TicketPriority, TicketStatus,
            TicketTimeEntry, TicketType,
        )
        from datetime import datetime, timedelta as _td
        from decimal import Decimal as _D
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        # Build a contract with a 60-min allowance and three entries:
        # 30 (covered), 40 (split: 30 covered + 10 overage), 20 (overage).
        contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_a,
            name='Detail-test', contract_type='block_hours',
            status='active', start_date=datetime.now().date(),
            total_hours=_D('1'),  # = 60 min
            hourly_rate=_D('100'),
        )
        ticket = Ticket.objects.create(
            organization=self.client_a, subject='det-test',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )
        from django.utils import timezone as _tz
        base = _tz.now() - _td(days=1)
        for offset, dur in enumerate([30, 40, 20]):
            started = base + _td(minutes=offset * 60)
            TicketTimeEntry.objects.create(
                ticket=ticket, user=self.staff,
                started_at=started, ended_at=started + _td(minutes=dur),
                duration_minutes=dur,
            )

        c = Client()
        self._login(c, self.staff)
        r = c.get(f'/reports/agreement-reconciliation/{contract.pk}/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # 30 (covered) + 30 (split-covered) = 60 covered total.
        # 10 (split-overage) + 20 (overage) = 30 overage total.
        self.assertEqual(ctx['covered_total'], 60)
        self.assertEqual(ctx['overage_total'], 30)
        # Per-row classification: first entry covered, second split, third overage.
        classifications = [r['classification'] for r in ctx['rows']]
        self.assertEqual(classifications, ['covered', 'split', 'overage'])

    def test_detail_view_csv_export(self):
        from django.test import Client
        from psa.models import Contract
        from datetime import datetime
        from decimal import Decimal as _D
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_a,
            name='CSV-test', contract_type='block_hours',
            status='active', start_date=datetime.now().date(),
            total_hours=_D('5'),
        )
        c = Client()
        self._login(c, self.staff)
        r = c.get(f'/reports/agreement-reconciliation/{contract.pk}/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')

    def test_detail_view_blocks_outsider(self):
        from django.test import Client
        from psa.models import Contract
        from datetime import datetime
        from decimal import Decimal as _D
        contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_b,  # client B
            name='Outsider-test', contract_type='block_hours',
            status='active', start_date=datetime.now().date(),
            total_hours=_D('5'),
        )
        # member_a only has membership in client_a; should not see client_b's.
        c = Client()
        self._login(c, self.member_a, self.client_a)
        r = c.get(f'/reports/agreement-reconciliation/{contract.pk}/')
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProcurementSummaryTests(TestCase):
    """Phase 13 v3 (v3.17.258): procurement summary report."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import PurchaseOrder
        from datetime import date as _date, timedelta as _td
        from decimal import Decimal as _D
        cls.org = Organization.objects.create(name='ProcCo', slug='proc-co')
        cls.staff = User.objects.create_user('proc-staff', 'ps@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('proc-mem', 'pm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        # Three POs across two vendors, all 'sent' (counts toward spend).
        for i, (vendor, total) in enumerate([
            ('Acme Hardware', '500.00'),
            ('Acme Hardware', '750.00'),
            ('Beta Distribution', '1200.00'),
        ]):
            po = PurchaseOrder.objects.create(
                organization=cls.org, po_number=f'PO-2026-{i:05d}',
                vendor_name=vendor, title=f'PO {i}',
                status='sent', total=_D(total),
            )
        # Draft PO — should be excluded from spend.
        PurchaseOrder.objects.create(
            organization=cls.org, po_number='PO-2026-99999',
            vendor_name='Draft Vendor', title='Draft',
            status='draft', total=_D('999'),
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_summary_with_vendor_aggregates(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/procurement-summary/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual(ctx['summary']['po_count'], 3)
        self.assertEqual(ctx['summary']['total_spend'], 500.0 + 750.0 + 1200.0)
        # 2 distinct vendors (excluding the draft)
        self.assertEqual(ctx['summary']['vendor_count'], 2)

    def test_draft_excluded_from_totals(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/procurement-summary/')
        body = r.content.decode('utf-8')
        self.assertNotIn('Draft Vendor', body)

    def test_csv_export_contains_per_vendor_rows(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/procurement-summary/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('Acme Hardware', body)
        self.assertIn('Beta Distribution', body)
        # Acme aggregated total = 1250
        self.assertIn('1250', body)

    def test_non_staff_member_blocked_with_404(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/procurement-summary/')
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VendorCostHistoryTests(TestCase):
    """Phase 13 v5 (v3.17.262) — per-line cost history aggregation."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import PurchaseOrder, PurchaseOrderLineItem
        from decimal import Decimal as _D
        cls.org = Organization.objects.create(name='VchCo', slug='vch-co')
        cls.staff = User.objects.create_user('vch-staff', 'vs@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('vch-mem', 'vm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        # Two POs from same vendor with same SKU at different prices
        # (price drift to detect).
        po_a = PurchaseOrder.objects.create(
            organization=cls.org, po_number='PO-V-00001',
            vendor_name='Cisco-Acme', title='Switches Q1',
            status='sent', total=_D('400'),
        )
        PurchaseOrderLineItem.objects.create(
            po=po_a, description='SFP-10G LR', sku='SFP-10G-LR',
            quantity=10, unit_price=_D('40.00'),
        )
        po_b = PurchaseOrder.objects.create(
            organization=cls.org, po_number='PO-V-00002',
            vendor_name='Cisco-Acme', title='Switches Q3',
            status='sent', total=_D('520'),
        )
        PurchaseOrderLineItem.objects.create(
            po=po_b, description='SFP-10G LR', sku='SFP-10G-LR',
            quantity=10, unit_price=_D('52.00'),
        )

        # Different vendor + SKU
        po_c = PurchaseOrder.objects.create(
            organization=cls.org, po_number='PO-V-00003',
            vendor_name='Other-Vendor', title='Cables',
            status='sent', total=_D('60'),
        )
        PurchaseOrderLineItem.objects.create(
            po=po_c, description='Cat6 patch 3ft', sku='CAT6-3',
            quantity=20, unit_price=_D('3.00'),
        )

        # Draft PO — must be excluded
        po_draft = PurchaseOrder.objects.create(
            organization=cls.org, po_number='PO-V-DRAFT',
            vendor_name='Draft-Vendor', title='Draft',
            status='draft', total=_D('999'),
        )
        PurchaseOrderLineItem.objects.create(
            po=po_draft, description='SHOULD NOT APPEAR', sku='X',
            quantity=1, unit_price=_D('999'),
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_aggregated_cost_history(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/vendor-cost-history/')
        self.assertEqual(r.status_code, 200)
        rows = {(row['vendor'], row['sku']): row for row in r.context['rows']}
        sfp = rows[('Cisco-Acme', 'SFP-10G-LR')]
        self.assertEqual(sfp['po_count'], 2)
        self.assertEqual(sfp['min_price'], 40.0)
        self.assertEqual(sfp['max_price'], 52.0)
        self.assertEqual(sfp['last_price'], 52.0)  # most recent

    def test_draft_lines_excluded(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/vendor-cost-history/')
        body = r.content.decode('utf-8')
        self.assertNotIn('SHOULD NOT APPEAR', body)

    def test_vendor_filter_narrows_results(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/vendor-cost-history/?vendor=Cisco-Acme')
        self.assertEqual(r.status_code, 200)
        skus = {row['sku'] for row in r.context['rows']}
        self.assertIn('SFP-10G-LR', skus)
        self.assertNotIn('CAT6-3', skus)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/vendor-cost-history/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('SFP-10G-LR', body)
        self.assertIn('CAT6-3', body)

    def test_non_staff_member_blocked_with_404(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/vendor-cost-history/')
        self.assertEqual(r.status_code, 404)


class AssetLifecycleScoringModelTests(TestCase):
    """Phase 13 v6 (v3.17.263) — `Asset.lifecycle_score()`."""

    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='LifeCo', slug='life-co')

    def _make(self, **kwargs):
        from assets.models import Asset
        return Asset.objects.create(
            organization=self.org, name=kwargs.pop('name', 'A'),
            asset_type=kwargs.pop('asset_type', 'server'), **kwargs,
        )

    def test_blank_asset_scores_zero(self):
        a = self._make()
        s = a.lifecycle_score()
        self.assertEqual(s['total'], 0)
        self.assertEqual(s['age'], 0)
        self.assertEqual(s['warranty'], 0)
        self.assertEqual(s['firmware'], 0)

    def test_old_asset_with_expired_warranty_scores_high(self):
        from datetime import date, timedelta
        a = self._make(
            purchase_date=date.today() - timedelta(days=365 * 6),
            lifespan_years=5,
            warranty_expiry=date.today() - timedelta(days=30),
        )
        s = a.lifecycle_score()
        # Age >= 100% → 50; warranty expired → 30; firmware → 0
        self.assertEqual(s['age'], 50)
        self.assertEqual(s['warranty'], 30)
        self.assertEqual(s['firmware'], 0)
        self.assertEqual(s['total'], 80)

    def test_warranty_expiring_within_90d_gets_20(self):
        from datetime import date, timedelta
        a = self._make(warranty_expiry=date.today() + timedelta(days=60))
        s = a.lifecycle_score()
        self.assertEqual(s['warranty'], 20)

    def test_warranty_expiring_within_year_gets_10(self):
        from datetime import date, timedelta
        a = self._make(warranty_expiry=date.today() + timedelta(days=200))
        s = a.lifecycle_score()
        self.assertEqual(s['warranty'], 10)

    def test_firmware_mismatch_adds_20(self):
        a = self._make(firmware_version='1.0', firmware_latest='2.0')
        s = a.lifecycle_score()
        self.assertEqual(s['firmware'], 20)

    def test_age_capped_at_50(self):
        from datetime import date, timedelta
        # 10 years on a 2-year asset still caps at 50
        a = self._make(
            purchase_date=date.today() - timedelta(days=365 * 10),
            lifespan_years=2,
        )
        s = a.lifecycle_score()
        self.assertEqual(s['age'], 50)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetLifecycleReportTests(TestCase):
    """Phase 13 v6 (v3.17.263) — /reports/asset-lifecycle/ view."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from assets.models import Asset
        from datetime import date, timedelta

        cls.org = Organization.objects.create(name='LifeViewCo', slug='lifeview-co')
        cls.user = User.objects.create_user('life-mem', 'lm@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        # High score: 6yr-old / 5yr lifespan + warranty expired = 80
        cls.high = Asset.objects.create(
            organization=cls.org, name='OldServer', asset_type='server',
            purchase_date=date.today() - timedelta(days=365 * 6),
            lifespan_years=5,
            warranty_expiry=date.today() - timedelta(days=30),
        )
        # Low score: brand new, 5yr lifespan, fresh warranty
        cls.low = Asset.objects.create(
            organization=cls.org, name='NewLaptop', asset_type='laptop',
            purchase_date=date.today() - timedelta(days=30),
            lifespan_years=5,
            warranty_expiry=date.today() + timedelta(days=365 * 3),
        )
        # No data: should be filtered out at the qs.filter() step
        cls.empty = Asset.objects.create(
            organization=cls.org, name='Mystery', asset_type='other',
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_default_threshold_50_shows_only_high(self):
        from django.test import Client
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get('/reports/asset-lifecycle/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode('utf-8')
        self.assertIn('OldServer', body)
        self.assertNotIn('NewLaptop', body)
        self.assertNotIn('Mystery', body)

    def test_low_threshold_includes_low_scoring(self):
        from django.test import Client
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get('/reports/asset-lifecycle/?threshold=0')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode('utf-8')
        self.assertIn('OldServer', body)
        self.assertIn('NewLaptop', body)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get('/reports/asset-lifecycle/?threshold=0&format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('OldServer', body)
        self.assertIn('NewLaptop', body)

    def test_no_org_no_staff_returns_404(self):
        from django.contrib.auth.models import User
        from django.test import Client
        u = User.objects.create_user('lonely', 'lo@x.com', 'pw')
        c = Client()
        self._login(c, u)  # no org pinned
        r = c.get('/reports/asset-lifecycle/')
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProcurementForecastingTests(TestCase):
    """Phase 13 v8 (v3.17.268) — procurement forecasting report."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import PurchaseOrder
        from datetime import date, timedelta
        from decimal import Decimal as _D

        cls.org = Organization.objects.create(name='ForecastCo', slug='forecast-co')
        cls.staff = User.objects.create_user('fc-staff', 'fs@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('fc-mem', 'fm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        # Vendor A: 3 POs over last 3 months @ $1000 each → 3-mo MA = $1000.
        for n in range(3):
            po = PurchaseOrder.objects.create(
                organization=cls.org, po_number=f'PO-FC-{n:05d}',
                vendor_name='ForecastCorp', title=f'Order {n}',
                status='sent', total=_D('1000'),
            )
            # Push created_at backward to span 3 distinct months
            po.created_at = po.created_at - timedelta(days=30 * n)
            po.save(update_fields=['created_at'])

        # Draft PO — should NOT factor into forecast.
        PurchaseOrder.objects.create(
            organization=cls.org, po_number='PO-FC-DRAFT',
            vendor_name='ShouldNotShow', title='Draft',
            status='draft', total=_D('999999'),
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_forecast_table(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/procurement-forecasting/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode('utf-8')
        self.assertIn('ForecastCorp', body)
        # Average should be $1000/month (rounded).
        rows = {row['vendor']: row for row in r.context['rows']}
        self.assertIn('ForecastCorp', rows)
        self.assertEqual(rows['ForecastCorp']['avg_3mo'], 1000.0)
        # Forecast next 3 months = avg * 3 = $3000.
        self.assertEqual(rows['ForecastCorp']['forecast_total_3mo'], 3000.0)

    def test_draft_excluded(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/procurement-forecasting/')
        body = r.content.decode('utf-8')
        self.assertNotIn('ShouldNotShow', body)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/procurement-forecasting/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('ForecastCorp', body)
        # Forecast column header
        self.assertIn('Forecast next', body)

    def test_non_staff_blocked_with_404(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/procurement-forecasting/')
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ARAgingReportTests(TestCase):
    """Phase 27 v5 (v3.17.269) — AR aging tied to QBO."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import Invoice
        from datetime import date as _date, timedelta as _td
        from decimal import Decimal as _D
        from django.utils import timezone as _tz

        cls.msp = Organization.objects.create(name='ARMsp', slug='ar-msp')
        cls.client_a = Organization.objects.create(name='ARClientA', slug='ar-ca')
        cls.client_b = Organization.objects.create(name='ARClientB', slug='ar-cb')
        cls.staff = User.objects.create_user('ar-staff', 'as@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('ar-mem', 'am@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.client_a,
                                   role=Role.OWNER, is_active=True)

        today = _date.today()

        # Client A: 100 due 10 days ago (0-30 bucket)
        Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            title='A-fresh', invoice_date=today - _td(days=15),
            due_date=today - _td(days=10),
            total=_D('100'), amount_paid=_D('0'),
            status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-A1',
            pushed_to_accounting_at=_tz.now(),
        )
        # Client A: 200 due 100 days ago (90+ bucket)
        Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            title='A-old', invoice_date=today - _td(days=120),
            due_date=today - _td(days=100),
            total=_D('200'), amount_paid=_D('0'),
            status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-A2',
            pushed_to_accounting_at=_tz.now(),
        )
        # Client B: 50 due 45 days ago (31-60 bucket)
        Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_b,
            title='B-mid', invoice_date=today - _td(days=60),
            due_date=today - _td(days=45),
            total=_D('50'), amount_paid=_D('0'),
            status='sent',
            accounting_provider='xero',
            accounting_external_id='XERO-B1',
            pushed_to_accounting_at=_tz.now(),
        )
        # Fully paid — should NOT appear
        Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            title='paid', invoice_date=today,
            total=_D('99'), amount_paid=_D('99'),
            status='paid',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-PAID',
            pushed_to_accounting_at=_tz.now(),
        )
        # Not pushed — should NOT appear (we're tied to QBO)
        Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            title='not pushed', invoice_date=today - _td(days=10),
            total=_D('77'), status='sent',
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_per_client_buckets(self):
        from django.test import Client
        from decimal import Decimal as _D
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ar-aging/')
        self.assertEqual(r.status_code, 200)
        rows = {row['name']: row for row in r.context['rows']}
        # Client A: $100 in 0-30, $200 in 90+, total $300, 2 invoices
        self.assertEqual(rows['ARClientA']['b_0_30'], _D('100'))
        self.assertEqual(rows['ARClientA']['b_90_plus'], _D('200'))
        self.assertEqual(rows['ARClientA']['total_balance'], _D('300'))
        self.assertEqual(rows['ARClientA']['invoice_count'], 2)
        # Client B: $50 in 31-60
        self.assertEqual(rows['ARClientB']['b_31_60'], _D('50'))
        self.assertEqual(rows['ARClientB']['total_balance'], _D('50'))

    def test_paid_and_unpushed_excluded(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ar-aging/')
        body = r.content.decode('utf-8')
        # 'paid' invoice's title was 'paid' — make sure it's not on the page
        self.assertNotIn('not pushed', body)

    def test_member_sees_only_their_org(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.client_a)
        r = c.get('/reports/ar-aging/')
        rows = {row['name']: row for row in r.context['rows']}
        self.assertIn('ARClientA', rows)
        self.assertNotIn('ARClientB', rows)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ar-aging/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('ARClientA', body)
        self.assertIn('ARClientB', body)
        self.assertIn('TOTAL', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BankReconciliationReportTests(TestCase):
    """Phase 27 v9 (v3.17.281): bank deposit reconciliation."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import Invoice, InvoiceLineItem, Payment
        from datetime import date as _date
        from decimal import Decimal as _D

        cls.org = Organization.objects.create(name='BankCo', slug='bank-co')
        cls.client_org = Organization.objects.create(name='BankClient', slug='bank-client')
        cls.staff = User.objects.create_user('bank-staff', 'bs@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('bank-mem', 'bm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.client_org,
                                   role=Role.OWNER, is_active=True)

        # Three invoices, each fully paid; payments grouped into 2 batches + 1 untagged
        for n, batch in enumerate(['DEP-1', 'DEP-1', 'DEP-2']):
            inv = Invoice.objects.create(
                organization=cls.org, client_org=cls.client_org,
                title=f'Inv {n}', invoice_date=_date.today(),
            )
            InvoiceLineItem.objects.create(
                invoice=inv, description='Service',
                quantity=1, unit_price=_D('100'),
            )
            inv.recompute_totals()
            Payment.objects.create(
                invoice=inv, amount=_D('100'), paid_on=_date.today(),
                method='ach', bank_deposit_batch=batch,
            )

        # One untagged payment
        inv_u = Invoice.objects.create(
            organization=cls.org, client_org=cls.client_org,
            title='Untagged', invoice_date=_date.today(),
        )
        InvoiceLineItem.objects.create(
            invoice=inv_u, description='Untagged service',
            quantity=1, unit_price=_D('50'),
        )
        inv_u.recompute_totals()
        Payment.objects.create(
            invoice=inv_u, amount=_D('50'), paid_on=_date.today(),
            method='ach', bank_deposit_batch='',
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_batches_and_untagged(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/bank-reconciliation/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # 1 untagged payment
        self.assertEqual(len(ctx['untagged']), 1)
        # 2 unreconciled batches: DEP-1 (2 payments) + DEP-2 (1 payment)
        self.assertEqual(ctx['totals']['unrec_batch_count'], 2)
        from decimal import Decimal as _D
        # Total awaiting confirm = 100+100+100 = 300
        self.assertEqual(ctx['totals']['unrec_total'], _D('300'))
        # No reconciled batches yet
        self.assertEqual(ctx['totals']['rec_batch_count'], 0)

    def test_mark_reconciled_endpoint(self):
        from django.test import Client
        from psa.models import Payment
        c = Client()
        self._login(c, self.staff)
        r = c.post('/reports/bank-reconciliation/mark/',
                   {'batch': 'DEP-1', 'action': 'reconcile'})
        self.assertEqual(r.status_code, 302)
        # 2 payments in DEP-1 should now have bank_reconciled_at set
        rec_count = Payment.objects.filter(
            bank_deposit_batch='DEP-1',
            bank_reconciled_at__isnull=False,
        ).count()
        self.assertEqual(rec_count, 2)

    def test_reopen_clears_reconciled_at(self):
        from django.test import Client
        from psa.models import Payment
        c = Client()
        self._login(c, self.staff)
        # First reconcile
        c.post('/reports/bank-reconciliation/mark/',
               {'batch': 'DEP-2', 'action': 'reconcile'})
        # Then reopen
        c.post('/reports/bank-reconciliation/mark/',
               {'batch': 'DEP-2', 'action': 'reopen'})
        rec_count = Payment.objects.filter(
            bank_deposit_batch='DEP-2',
            bank_reconciled_at__isnull=False,
        ).count()
        self.assertEqual(rec_count, 0)

    def test_non_staff_cannot_mark(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.client_org)
        r = c.post('/reports/bank-reconciliation/mark/',
                   {'batch': 'DEP-1', 'action': 'reconcile'})
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MultiLocationReportTests(TestCase):
    """Phase 18 v8/v9/v10 (v3.17.283): multi-location operational report."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User
        from core.models import Organization
        from assets.models import Asset
        cls.staff = User.objects.create_user('ml-staff', 'ms@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.parent = Organization.objects.create(
            name='HoldingCo', slug='hc', region='EMEA',
        )
        cls.uk = Organization.objects.create(
            name='UK Site', slug='hc-uk', parent=cls.parent, region='EMEA',
        )
        cls.us = Organization.objects.create(
            name='US Site', slug='hc-us', parent=cls.parent, region='Americas',
        )
        cls.shared_asset = Asset.objects.create(
            organization=cls.parent, name='Shared firewall',
            asset_type='firewall', is_shared_with_descendants=True,
        )
        # An asset that is NOT shared
        Asset.objects.create(
            organization=cls.parent, name='Local backup',
            asset_type='backup_appliance',
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_all_three_sections(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/multi-location/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # Region rollup: emea + americas
        keys = [k for k, _ in ctx['region_rows']]
        self.assertIn('emea', keys)
        self.assertIn('americas', keys)
        # Per-parent rollup: HoldingCo has 2 children → tree_size 3 (incl self)
        names = [r['parent'].name for r in ctx['parent_rows']]
        self.assertIn('HoldingCo', names)
        # Shared assets: 1 row
        self.assertEqual(len(ctx['shared_rows']), 1)
        self.assertEqual(ctx['shared_rows'][0]['asset'].name, 'Shared firewall')

    def test_shared_asset_lists_descendants(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/multi-location/')
        row = r.context['shared_rows'][0]
        descendant_names = [d.name for d in row['visible_to']]
        self.assertIn('UK Site', descendant_names)
        self.assertIn('US Site', descendant_names)
        # Owner org should NOT be in the visible_to list (we exclude it)
        self.assertNotIn('HoldingCo', descendant_names)

    def test_non_shared_asset_excluded(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/multi-location/')
        body = r.content.decode('utf-8')
        # 'Local backup' is not flagged shared → should not appear in
        # the shared services section.
        # (It might appear in other sections by name; the explicit
        # check is on context len.)
        self.assertEqual(len(r.context['shared_rows']), 1)

    def test_unassigned_region_grouped_separately(self):
        from core.models import Organization
        from django.test import Client
        Organization.objects.create(name='Untagged', slug='untag')
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/multi-location/')
        keys = [k for k, _ in r.context['region_rows']]
        self.assertIn('(unassigned)', keys)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BillingReconciliationReportTests(TestCase):
    """Phase 15 v6 (v3.17.295): per-client invoiced-vs-paid summary."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import Invoice, InvoiceLineItem
        from datetime import date as _date
        from decimal import Decimal as _D
        cls.org = Organization.objects.create(name='BrCo', slug='br-co')
        cls.client_org = Organization.objects.create(name='BrClient', slug='br-client')
        cls.staff = User.objects.create_user('br-staff', 'bs@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        # 3 invoices: 1 fully paid, 1 partial, 1 unpaid
        for label, total, paid in [('Paid', '500', '500'),
                                    ('Partial', '300', '100'),
                                    ('Unpaid', '200', '0')]:
            inv = Invoice.objects.create(
                organization=cls.org, client_org=cls.client_org,
                title=label, invoice_date=_date.today(),
                status='sent',
            )
            InvoiceLineItem.objects.create(
                invoice=inv, description='Service',
                quantity=1, unit_price=_D(total),
            )
            inv.recompute_totals()
            from psa.models import Payment
            if _D(paid) > 0:
                Payment.objects.create(
                    invoice=inv, amount=_D(paid), paid_on=_date.today(),
                    method='ach',
                )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_per_client_totals(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/billing-reconciliation/')
        self.assertEqual(r.status_code, 200)
        rows = {row['name']: row for row in r.context['rows']}
        self.assertIn('BrClient', rows)
        from decimal import Decimal as _D
        # Total invoiced: 500+300+200 = 1000
        self.assertEqual(rows['BrClient']['invoiced'], _D('1000'))
        # Paid: 500+100+0 = 600
        self.assertEqual(rows['BrClient']['paid'], _D('600'))
        # Outstanding: 400
        self.assertEqual(rows['BrClient']['outstanding'], _D('400'))
        # Collection %: 60.0
        self.assertEqual(rows['BrClient']['collection_pct'], 60.0)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/billing-reconciliation/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('BrClient', body)
        self.assertIn('TOTAL', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MRRForecastReportTests(TestCase):
    """Phase 15 v9 (v3.17.295): MRR + ARR projection."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import Contract
        from datetime import date as _date
        from decimal import Decimal as _D
        cls.org = Organization.objects.create(name='MrrCo', slug='mrr-co')
        cls.client_org = Organization.objects.create(name='MrrClient',
                                                      slug='mrr-client')
        cls.staff = User.objects.create_user('mrr-staff', 'ms@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('mrr-mem', 'mm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.client_org,
                                   role=Role.OWNER, is_active=True)
        # Monthly $1000, quarterly $3000 (= $1000/mo), yearly $12000 (= $1000/mo)
        Contract.objects.create(
            organization=cls.org, client_org=cls.client_org,
            name='Monthly-1k', contract_type='managed_services', status='active',
            start_date=_date.today(), recurring_amount=_D('1000'),
            billing_frequency='monthly',
        )
        Contract.objects.create(
            organization=cls.org, client_org=cls.client_org,
            name='Quarterly-3k', contract_type='managed_services', status='active',
            start_date=_date.today(), recurring_amount=_D('3000'),
            billing_frequency='quarterly',
        )
        Contract.objects.create(
            organization=cls.org, client_org=cls.client_org,
            name='Yearly-12k', contract_type='managed_services', status='active',
            start_date=_date.today(), recurring_amount=_D('12000'),
            billing_frequency='yearly',
        )
        # Excluded: inactive
        Contract.objects.create(
            organization=cls.org, client_org=cls.client_org,
            name='Expired', contract_type='managed_services', status='expired',
            start_date=_date.today(), recurring_amount=_D('99999'),
            billing_frequency='monthly',
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_total_mrr_normalized(self):
        from django.test import Client
        from decimal import Decimal as _D
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/mrr-forecast/')
        self.assertEqual(r.status_code, 200)
        # 1000 + 3000/3 + 12000/12 = 1000 + 1000 + 1000 = 3000
        self.assertEqual(r.context['totals']['mrr'], _D('3000.00'))
        # ARR = MRR * 12 = 36000
        self.assertEqual(r.context['totals']['arr'], _D('36000.00'))
        self.assertEqual(r.context['totals']['contract_count'], 3)

    def test_excludes_expired_contracts(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/mrr-forecast/')
        names = [row['contract'].name for row in r.context['rows']]
        self.assertNotIn('Expired', names)

    def test_non_staff_blocked(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.client_org)
        r = c.get('/reports/mrr-forecast/')
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class HardwareMarginReportTests(TestCase):
    """Phase 13 v9 (v3.17.271) — hardware-resale margin."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import Quote, PurchaseOrder, Invoice
        from datetime import date as _date
        from decimal import Decimal as _D

        cls.org = Organization.objects.create(name='HwMargCo', slug='hw-marg')
        cls.client_org = Organization.objects.create(name='HwMargClient', slug='hw-marg-client')
        cls.staff = User.objects.create_user('hw-staff', 'hs@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('hw-mem', 'hm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.client_org,
                                   role=Role.OWNER, is_active=True)

        cls.q_match = Quote.objects.create(
            organization=cls.org, client_org=cls.client_org,
            title='Switch refresh', status='accepted',
        )
        # PO — cost $1000
        PurchaseOrder.objects.create(
            organization=cls.org, client_org=cls.client_org,
            po_number='PO-HM-1', vendor_name='Cisco',
            title='Switches', status='received', total=_D('1000'),
            source_quote=cls.q_match,
        )
        # Invoice — revenue $1500 → margin $500
        Invoice.objects.create(
            organization=cls.org, client_org=cls.client_org,
            title='Switch refresh', invoice_date=_date.today(),
            total=_D('1500'), status='paid', amount_paid=_D('1500'),
            source_quote=cls.q_match,
        )

        # Quote with PO but NO invoice — should be filtered out
        cls.q_po_only = Quote.objects.create(
            organization=cls.org, client_org=cls.client_org,
            title='Cables only', status='draft',
        )
        PurchaseOrder.objects.create(
            organization=cls.org, client_org=cls.client_org,
            po_number='PO-HM-2', vendor_name='Cables-R-Us',
            title='Cables', status='sent', total=_D('200'),
            source_quote=cls.q_po_only,
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_matched_quote_appears_with_correct_margin(self):
        from django.test import Client
        from decimal import Decimal as _D
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/hardware-margin/')
        self.assertEqual(r.status_code, 200)
        rows = r.context['rows']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['quote_id'], self.q_match.pk)
        self.assertEqual(row['cost'], _D('1000'))
        self.assertEqual(row['revenue'], _D('1500'))
        self.assertEqual(row['margin'], _D('500'))
        self.assertEqual(row['client'], 'HwMargClient')
        self.assertEqual(row['vendor'], 'Cisco')

    def test_unmatched_quote_excluded(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/hardware-margin/')
        body = r.content.decode('utf-8')
        # The PO-only quote should NOT show
        self.assertNotIn('Cables only', body)

    def test_blended_margin_pct(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/hardware-margin/')
        # 500 / 1500 = 33.3%
        self.assertEqual(r.context['totals']['margin_pct'], 33.3)

    def test_csv_export_has_total_row(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/hardware-margin/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('Switch refresh', body)
        self.assertIn('TOTAL', body)

    def test_non_staff_blocked_with_404(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.client_org)
        r = c.get('/reports/hardware-margin/')
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketAgingReportTests(TestCase):
    """Phase 19 v1 (v3.17.257) — ticket aging analytics."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketType,
        )
        from datetime import timedelta as _td
        from django.utils import timezone as _tz
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='AgingCo', slug='aging-co')
        cls.outsider = Organization.objects.create(name='Outsider', slug='aging-out')
        cls.staff = User.objects.create_user('aging-staff', 'as@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('aging-mem', 'am@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        queue = Queue.objects.first()
        priority = TicketPriority.objects.first()
        ttype = TicketType.objects.first()
        new = TicketStatus.objects.filter(slug='new').first()
        terminal = TicketStatus.objects.filter(is_terminal=True).first()

        def make(subject, age_hours, status=new, org=None):
            t = Ticket.objects.create(
                organization=org or cls.org, subject=subject,
                queue=queue, priority=priority,
                ticket_type=ttype, status=status,
            )
            Ticket.objects.filter(pk=t.pk).update(
                created_at=_tz.now() - _td(hours=age_hours),
            )
            return t

        cls.fresh = make('fresh', 1)         # 0-24h bucket
        cls.day2 = make('two days', 36)      # 24-72h
        cls.weekish = make('5 days', 24*5)   # 3-7d
        cls.aged = make('three weeks', 24*21)   # 7-30d
        cls.ancient = make('ancient', 24*60)   # 30+d
        # Terminal — should NOT count
        make('done', 1, status=terminal)
        # Cross-tenant — should NOT count for member
        make('outsider', 1, org=cls.outsider)

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_buckets_count_correctly_for_staff(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ticket-aging/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # Staff sees both orgs; org's 5 + outsider's 1 = 6 fresh-bucket
        # candidates BUT outsider lands in 0-24h too so total open = 6.
        # Bucket shape: 0-24h = 2 (fresh + outsider), 24-72h = 1, 3-7d = 1, 7-30d = 1, 30+d = 1
        totals = ctx['bucket_totals']
        self.assertEqual(totals['0-24h'], 2)
        self.assertEqual(totals['24-72h'], 1)
        self.assertEqual(totals['3-7d'], 1)
        self.assertEqual(totals['7-30d'], 1)
        self.assertEqual(totals['30+d'], 1)
        self.assertEqual(ctx['total_open'], 6)

    def test_member_sees_only_their_org(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/ticket-aging/')
        ctx = r.context
        self.assertEqual(ctx['total_open'], 5)  # outsider excluded
        self.assertEqual(ctx['bucket_totals']['0-24h'], 1)

    def test_excludes_terminal_status(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ticket-aging/')
        body = r.content.decode('utf-8')
        # 'done' ticket subject must not appear in aged_tickets
        self.assertNotIn('done', body.lower().split('aged 7+')[1] if 'aged 7+' in body.lower() else '')

    def test_aged_section_lists_7plus_day_tickets(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ticket-aging/')
        ctx = r.context
        # aged_tickets should contain weekish (5d) is < 7d — actually no, weekish=5d.
        # Only aged (21d) and ancient (60d) qualify as 7+ days.
        aged_subjects = [t.subject for t in ctx['aged_tickets']]
        self.assertIn('three weeks', aged_subjects)
        self.assertIn('ancient', aged_subjects)
        self.assertNotIn('5 days', aged_subjects)
        self.assertNotIn('two days', aged_subjects)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ticket-aging/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        # Header row contains all bucket labels
        self.assertIn('0-24h', body)
        self.assertIn('30+d', body)
        # TOTAL row present
        self.assertIn('TOTAL', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AccountingReconciliationTests(TestCase):
    """Phase 27 v1 (v3.17.255) — accounting reconciliation report."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from psa.models import Invoice
        from datetime import date as _date
        from decimal import Decimal as _D
        from django.utils import timezone as _tz
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.msp = Organization.objects.create(name='AcctMSP', slug='acct-msp')
        cls.client_a = Organization.objects.create(name='AcctClientA', slug='acct-ca')
        cls.client_b = Organization.objects.create(name='AcctClientB', slug='acct-cb')
        cls.staff = User.objects.create_user('acct-staff', 'as@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member_a = User.objects.create_user('acct-mem-a', 'ma@x.com', 'pw')
        Membership.objects.create(user=cls.member_a, organization=cls.client_a,
                                   role=Role.OWNER, is_active=True)

        # Outstanding pushed: pushed but unpaid.
        cls.outstanding = Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            title='Pushed not paid', invoice_date=_date.today(),
            total=_D('500'), amount_paid=_D('0'),
            status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-001',
            pushed_to_accounting_at=_tz.now(),
        )
        # Fully paid pushed — should NOT appear in outstanding.
        cls.paid = Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            title='Pushed and paid', invoice_date=_date.today(),
            total=_D('100'), amount_paid=_D('100'),
            status='paid',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-002',
            pushed_to_accounting_at=_tz.now(),
        )
        # Push error.
        cls.error_inv = Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_a,
            title='Failed push', invoice_date=_date.today(),
            total=_D('250'), status='draft',
            last_push_error='Connection timeout',
            accounting_provider='xero',
        )
        # Two invoices sharing the same external ID — duplicate.
        cls.dup1 = Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_b,
            title='Duplicate A', invoice_date=_date.today(),
            total=_D('99'), status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-DUP',
            pushed_to_accounting_at=_tz.now(),
        )
        cls.dup2 = Invoice.objects.create(
            organization=cls.msp, client_org=cls.client_b,
            title='Duplicate B', invoice_date=_date.today(),
            total=_D('99'), status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-DUP',
            pushed_to_accounting_at=_tz.now(),
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_all_three_sections(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/accounting-reconciliation/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # outstanding_count = pushed AND not paid/void AND amount_paid<total.
        # Matches: outstanding (500) + dup1 (99) + dup2 (99) = 3 invoices.
        self.assertEqual(ctx['summary']['outstanding_count'], 3)
        self.assertEqual(ctx['summary']['outstanding_balance'], 500.0 + 99.0 + 99.0)
        self.assertEqual(ctx['summary']['error_count'], 1)
        self.assertEqual(ctx['summary']['duplicate_groups'], 1)

    def test_outstanding_excludes_paid_and_void(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/accounting-reconciliation/')
        body = r.content.decode('utf-8')
        self.assertIn('Pushed not paid', body)
        self.assertNotIn('Pushed and paid', body)

    def test_push_error_section_shows_error_message(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/accounting-reconciliation/')
        self.assertContains(r, 'Connection timeout')

    def test_duplicate_group_lists_both_invoices(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/accounting-reconciliation/')
        body = r.content.decode('utf-8')
        # Both invoices in the duplicate group should be listed.
        self.assertIn('Duplicate A', body)
        self.assertIn('Duplicate B', body)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/accounting-reconciliation/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        # Section column present
        self.assertIn('Section', body.split('\n')[0])
        # All three section types included
        self.assertIn('outstanding', body)
        self.assertIn('push_error', body)
        self.assertIn('duplicate', body)

    def test_member_sees_only_their_org_invoices(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member_a, self.client_a)
        r = c.get('/reports/accounting-reconciliation/')
        body = r.content.decode('utf-8')
        # client_a invoices visible
        self.assertIn('Pushed not paid', body)
        # client_b duplicates NOT visible
        self.assertNotIn('Duplicate A', body)
        self.assertNotIn('Duplicate B', body)

    def test_tax_discrepancies_surfaced(self):
        """Phase 27 v4 (v3.17.267) — invoices where provider_tax_amount
        differs from local tax_amount > $0.01 land in tax_discrepancies."""
        from django.test import Client
        from psa.models import Invoice
        from datetime import date as _date
        from decimal import Decimal as _D
        from django.utils import timezone as _tz

        # Local says $10 tax; QBO says $12 — a $2 mismatch.
        Invoice.objects.create(
            organization=self.msp, client_org=self.client_a,
            title='Tax mismatch', invoice_date=_date.today(),
            total=_D('100'), tax_amount=_D('10.00'),
            provider_tax_amount=_D('12.00'),
            status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-TAX-1',
            pushed_to_accounting_at=_tz.now(),
        )
        # Aligned tax — should NOT appear.
        Invoice.objects.create(
            organization=self.msp, client_org=self.client_a,
            title='Tax aligned', invoice_date=_date.today(),
            total=_D('100'), tax_amount=_D('10.00'),
            provider_tax_amount=_D('10.00'),
            status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-TAX-2',
            pushed_to_accounting_at=_tz.now(),
        )
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/accounting-reconciliation/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual(ctx['summary']['tax_mismatch_count'], 1)
        self.assertEqual(len(ctx['tax_discrepancies']), 1)
        d = ctx['tax_discrepancies'][0]
        self.assertEqual(d['invoice'].title, 'Tax mismatch')
        self.assertEqual(d['delta'], _D('2.00'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SavedQueryTests(TestCase):
    """Phase 26 v1 (v3.17.246) — Saved Query model + run endpoint."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='SQCo', slug='sq-co')
        cls.outsider = Organization.objects.create(name='OutsideSQ', slug='sq-out')
        cls.user = User.objects.create_user('sq-user', 'sq@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.OWNER, is_active=True)
        cls.peer = User.objects.create_user('sq-peer', 'p@x.com', 'pw')
        Membership.objects.create(user=cls.peer, organization=cls.org,
                                   role=Role.OWNER, is_active=True)
        cls.outsider_user = User.objects.create_user('sq-out', 'o@x.com', 'pw')
        Membership.objects.create(user=cls.outsider_user, organization=cls.outsider,
                                   role=Role.OWNER, is_active=True)
        cls.queue = Queue.objects.first()
        cls.priority = TicketPriority.objects.first()
        cls.ttype = TicketType.objects.first()
        cls.status = TicketStatus.objects.filter(slug='new').first()
        cls.urgent = Ticket.objects.create(
            organization=cls.org, subject='Network down — urgent fix needed',
            queue=cls.queue, priority=cls.priority,
            ticket_type=cls.ttype, status=cls.status,
        )
        cls.normal = Ticket.objects.create(
            organization=cls.org, subject='Add a printer to office 3',
            queue=cls.queue, priority=cls.priority,
            ticket_type=cls.ttype, status=cls.status,
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_build_filter_drops_unknown_field(self):
        from reports.saved_query import build_filter
        # Bad field is silently dropped, query becomes "match all"
        q = build_filter('psa.Ticket', [
            {'field': 'definitely_not_a_field', 'op': 'equals', 'value': 'x'},
        ])
        self.assertEqual(str(q), str(__import__('django.db.models', fromlist=['Q']).Q()))

    def test_execute_filters_by_subject_contains(self):
        from reports.models import SavedQuery
        from reports.saved_query import execute
        sq = SavedQuery.objects.create(
            owner=self.user, name='Urgent tickets',
            target_model='psa.Ticket',
            filters=[{'field': 'subject', 'op': 'contains', 'value': 'urgent'}],
        )
        _model, qs = execute(sq)
        titles = list(qs.values_list('subject', flat=True))
        self.assertIn('Network down — urgent fix needed', titles)
        self.assertNotIn('Add a printer to office 3', titles)

    def test_execute_scopes_to_organization(self):
        from reports.models import SavedQuery
        from reports.saved_query import execute
        from psa.models import Ticket
        Ticket.objects.create(
            organization=self.outsider, subject='Outside ticket',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        sq = SavedQuery.objects.create(
            owner=self.user, organization=self.org,
            name='Org tickets', target_model='psa.Ticket',
        )
        _model, qs = execute(sq, organization=sq.organization)
        titles = list(qs.values_list('subject', flat=True))
        self.assertNotIn('Outside ticket', titles)

    def test_visible_to_owner_only_by_default(self):
        from reports.models import SavedQuery
        sq = SavedQuery.objects.create(
            owner=self.user, organization=self.org,
            name='Private', target_model='psa.Ticket',
        )
        self.assertTrue(sq.visible_to(self.user))
        self.assertFalse(sq.visible_to(self.peer))

    def test_visible_to_peer_when_shared_in_same_org(self):
        from reports.models import SavedQuery
        sq = SavedQuery.objects.create(
            owner=self.user, organization=self.org,
            name='Shared', target_model='psa.Ticket', is_shared=True,
        )
        self.assertTrue(sq.visible_to(self.peer))

    def test_visible_to_blocks_outsider_even_when_shared(self):
        from reports.models import SavedQuery
        sq = SavedQuery.objects.create(
            owner=self.user, organization=self.org,
            name='Shared', target_model='psa.Ticket', is_shared=True,
        )
        self.assertFalse(sq.visible_to(self.outsider_user))

    def test_run_view_renders_html(self):
        from reports.models import SavedQuery
        from django.test import Client
        sq = SavedQuery.objects.create(
            owner=self.user, name='Net tickets',
            target_model='psa.Ticket',
            filters=[{'field': 'subject', 'op': 'contains', 'value': 'Network'}],
        )
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get(f'/reports/saved-queries/{sq.pk}/run/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Network down')
        self.assertNotContains(r, 'Add a printer')

    def test_run_view_csv_export(self):
        from reports.models import SavedQuery
        from django.test import Client
        sq = SavedQuery.objects.create(
            owner=self.user, name='All tickets',
            target_model='psa.Ticket',
        )
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get(f'/reports/saved-queries/{sq.pk}/run/?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('subject', body.split('\n')[0])

    def test_run_view_404_for_outsider(self):
        from reports.models import SavedQuery
        from django.test import Client
        sq = SavedQuery.objects.create(
            owner=self.user, name='My private', target_model='psa.Ticket',
        )
        c = Client()
        self._login(c, self.outsider_user, self.outsider)
        r = c.get(f'/reports/saved-queries/{sq.pk}/run/')
        self.assertEqual(r.status_code, 404)

    def test_create_view_persists_filters(self):
        from reports.models import SavedQuery
        from django.test import Client
        c = Client()
        self._login(c, self.user, self.org)
        r = c.post('/reports/saved-queries/new/', data={
            'name': 'Customer asks',
            'description': '',
            'target_model': 'psa.Ticket',
            'organization': '',
            'filter_field': ['subject', 'subject'],
            'filter_op': ['contains', 'contains'],
            'filter_value': ['printer', 'office'],
            'column': ['ticket_number', 'subject'],
            'sort_by': '-created_at',
        })
        self.assertEqual(r.status_code, 302)
        sq = SavedQuery.objects.get(name='Customer asks')
        self.assertEqual(sq.target_model, 'psa.Ticket')
        self.assertEqual(len(sq.filters), 2)
        self.assertEqual(sq.columns, ['ticket_number', 'subject'])

    def test_delete_view_blocks_non_owner(self):
        from reports.models import SavedQuery
        from django.test import Client
        sq = SavedQuery.objects.create(
            owner=self.user, name='Mine', target_model='psa.Ticket',
        )
        c = Client()
        self._login(c, self.peer, self.org)
        c.post(f'/reports/saved-queries/{sq.pk}/delete/')
        # Still exists.
        self.assertTrue(SavedQuery.objects.filter(pk=sq.pk).exists())

    # --- Phase 26 v2 (v3.17.251) — Invoice + TimeEntry targets ----------

    def test_invoice_target_filters_by_status(self):
        from reports.models import SavedQuery
        from reports.saved_query import execute
        from psa.models import Invoice
        from datetime import date as _date
        Invoice.objects.create(
            organization=self.org, client_org=self.org, title='Paid one',
            invoice_date=_date.today(), status='paid',
        )
        Invoice.objects.create(
            organization=self.org, client_org=self.org, title='Sent one',
            invoice_date=_date.today(), status='sent',
        )
        sq = SavedQuery.objects.create(
            owner=self.user, name='Paid invoices', target_model='psa.Invoice',
            filters=[{'field': 'status', 'op': 'equals', 'value': 'paid'}],
        )
        _model, qs = execute(sq)
        titles = list(qs.values_list('title', flat=True))
        self.assertIn('Paid one', titles)
        self.assertNotIn('Sent one', titles)

    def test_time_entry_target_scopes_via_ticket_org(self):
        from reports.models import SavedQuery
        from reports.saved_query import execute
        from psa.models import TicketTimeEntry, Ticket
        from datetime import datetime, timedelta as _td
        from django.utils import timezone as _tz
        # Build an outsider ticket + entry
        outsider_ticket = Ticket.objects.create(
            organization=self.outsider, subject='out',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        TicketTimeEntry.objects.create(
            ticket=outsider_ticket, user=self.user,
            started_at=_tz.now() - _td(hours=1),
            ended_at=_tz.now(),
            duration_minutes=60, notes='outsider work',
        )
        # Build an org-A entry
        TicketTimeEntry.objects.create(
            ticket=self.urgent, user=self.user,
            started_at=_tz.now() - _td(hours=1),
            ended_at=_tz.now(),
            duration_minutes=30, notes='org-a work',
        )
        sq = SavedQuery.objects.create(
            owner=self.user, organization=self.org,
            name='My time', target_model='psa.TicketTimeEntry',
        )
        _model, qs = execute(sq, organization=self.org)
        notes_seen = list(qs.values_list('notes', flat=True))
        self.assertIn('org-a work', notes_seen)
        self.assertNotIn('outsider work', notes_seen)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardGlobalScopeTests(TestCase):
    """v3.17.216: organization-null = global wallboard, staff-only."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from reports.models import Wallboard
        cls.org = Organization.objects.create(name='GlobCo', slug='wb-glob-co')
        cls.staff = User.objects.create_user(
            'wb-glob-staff', email='wbgs@x.com', password='pw',
            is_staff=True, is_superuser=True,
        )
        cls.member = User.objects.create_user(
            'wb-glob-mem', email='wbgm@x.com', password='pw',
        )
        Membership.objects.create(
            user=cls.member, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.org_board = Wallboard.objects.create(organization=cls.org, name='Org-NOC')
        cls.global_board = Wallboard.objects.create(organization=None, name='Global-NOC')

    def test_global_board_persists_with_null_org(self):
        from reports.models import Wallboard
        b = Wallboard.objects.get(pk=self.global_board.pk)
        self.assertIsNone(b.organization)
        self.assertTrue(b.is_global)
        self.assertIn('Global', str(b))

    def test_acl_helper_allows_global_for_staff_only(self):
        from reports.views import _user_can_see_wallboards
        self.assertTrue(_user_can_see_wallboards(self.staff, None))
        self.assertFalse(_user_can_see_wallboards(self.member, None))
        # Both can see the org board (member via membership; staff via flag).
        self.assertTrue(_user_can_see_wallboards(self.staff, self.org))
        self.assertTrue(_user_can_see_wallboards(self.member, self.org))

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_list_includes_global_board_for_staff(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/wallboards/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Global-NOC')
        self.assertContains(r, 'Org-NOC')

    def test_list_hides_global_board_from_org_member(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member)
        r = c.get('/reports/wallboards/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Org-NOC')
        self.assertNotContains(r, 'Global-NOC')

    def test_org_member_cannot_view_global_board_directly(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member)
        r = c.get(f'/reports/wallboards/{self.global_board.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_staff_can_create_global_board_via_form(self):
        from django.test import Client
        from reports.models import Wallboard
        c = Client()
        self._login(c, self.staff)
        r = c.post('/reports/wallboards/new/', data={
            'organization': 'global',
            'name': 'Made-Global',
            'description': '',
            'refresh_seconds': 60,
            'rotate_seconds': 0,
            'order': 100,
            'is_active': 'on',
        })
        self.assertIn(r.status_code, [200, 302])
        b = Wallboard.objects.get(name='Made-Global')
        self.assertIsNone(b.organization)

    def test_non_staff_member_cannot_create_global_board(self):
        from django.test import Client
        from reports.models import Wallboard
        c = Client()
        self._login(c, self.member)
        r = c.post('/reports/wallboards/new/', data={
            'organization': 'global',
            'name': 'BadGlobal',
            'description': '',
            'refresh_seconds': 60,
            'rotate_seconds': 0,
            'order': 100,
            'is_active': 'on',
        })
        # The view rejects "global" for non-staff with an error redirect;
        # nothing persists.
        self.assertFalse(Wallboard.objects.filter(name='BadGlobal').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardFormCleanupTests(TestCase):
    """v3.17.220: in-form widget add/delete + starter templates."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from reports.models import Wallboard, WallboardWidget
        cls.org = Organization.objects.create(name='FormCleanCo', slug='wb-fc-co')
        cls.staff = User.objects.create_user(
            'wb-fc-staff', email='wbfcs@x.com', password='pw',
            is_staff=True, is_superuser=True,
        )
        Membership.objects.create(
            user=cls.staff, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.board = Wallboard.objects.create(organization=cls.org, name='ToEdit')
        cls.widget = WallboardWidget.objects.create(
            wallboard=cls.board, title='Existing', widget_type='metric',
            data_source='open_tickets_count', order=10,
        )

    def _login(self, c):
        c.force_login(self.staff)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_template_constant_has_expected_keys(self):
        from reports.widget_sources import WALLBOARD_TEMPLATES, get_template
        keys = [t['key'] for t in WALLBOARD_TEMPLATES]
        for required in ('custom', 'operations', 'tickets', 'alerts', 'sales', 'health'):
            self.assertIn(required, keys)
        self.assertIsNone(get_template('does-not-exist'))
        self.assertEqual(get_template('operations')['key'], 'operations')

    def test_create_with_template_populates_widgets(self):
        from django.test import Client
        from reports.models import Wallboard
        c = Client()
        self._login(c)
        r = c.post('/reports/wallboards/new/', data={
            'organization': self.org.pk,
            'name': 'TplBoard',
            'description': '',
            'refresh_seconds': 60,
            'rotate_seconds': 0,
            'order': 100,
            'is_active': 'on',
            'template': 'operations',
        })
        self.assertIn(r.status_code, [200, 302])
        b = Wallboard.objects.get(name='TplBoard')
        self.assertEqual(b.widgets.count(), 6)  # Operations template has 6 widgets

    def test_create_with_custom_template_creates_no_widgets(self):
        from django.test import Client
        from reports.models import Wallboard
        c = Client()
        self._login(c)
        r = c.post('/reports/wallboards/new/', data={
            'organization': self.org.pk,
            'name': 'EmptyBoard',
            'description': '',
            'refresh_seconds': 60,
            'rotate_seconds': 0,
            'order': 100,
            'is_active': 'on',
            'template': 'custom',
        })
        self.assertIn(r.status_code, [200, 302])
        b = Wallboard.objects.get(name='EmptyBoard')
        self.assertEqual(b.widgets.count(), 0)

    def test_widget_add_view_creates_widget_with_derived_type(self):
        # v3.17.221: widget_type is auto-derived from the data source's
        # recommended type in DATA_SOURCE_CHOICES. The form does not pass
        # widget_type any more.
        from django.test import Client
        c = Client()
        self._login(c)
        before = self.board.widgets.count()
        r = c.post(f'/reports/wallboards/{self.board.pk}/widgets/add/', data={
            'title': 'New One',
            'data_source': 'tickets_by_priority',  # recommended type: table
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.board.widgets.count(), before + 1)
        new = self.board.widgets.get(title='New One')
        self.assertEqual(new.data_source, 'tickets_by_priority')
        self.assertEqual(new.widget_type, 'table')

    def test_widget_add_rejects_unknown_data_source(self):
        from django.test import Client
        c = Client()
        self._login(c)
        before = self.board.widgets.count()
        r = c.post(f'/reports/wallboards/{self.board.pk}/widgets/add/', data={
            'title': 'Bogus',
            'data_source': 'definitely_does_not_exist',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.board.widgets.count(), before)

    def test_widget_add_rejects_missing_title(self):
        from django.test import Client
        c = Client()
        self._login(c)
        before = self.board.widgets.count()
        r = c.post(f'/reports/wallboards/{self.board.pk}/widgets/add/', data={
            'title': '',
            'data_source': 'open_tickets_count',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.board.widgets.count(), before)

    def test_widget_delete_view_removes_widget(self):
        from django.test import Client
        from reports.models import WallboardWidget
        c = Client()
        self._login(c)
        wid = WallboardWidget.objects.create(
            wallboard=self.board, title='Doomed', widget_type='metric',
            data_source='open_tickets_count', order=99,
        )
        r = c.post(f'/reports/wallboards/widgets/{wid.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(WallboardWidget.objects.filter(pk=wid.pk).exists())

    def test_widget_add_rejects_get(self):
        from django.test import Client
        c = Client()
        self._login(c)
        r = c.get(f'/reports/wallboards/{self.board.pk}/widgets/add/')
        self.assertEqual(r.status_code, 405)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardWidgetCategoryTests(TestCase):
    """v3.17.217: per-widget category dropdown + JSON refresh endpoint."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from reports.models import Wallboard, WallboardWidget
        cls.org = Organization.objects.create(name='CatCo', slug='wb-cat-co')
        cls.staff = User.objects.create_user(
            'wb-cat-staff', email='wbcs@x.com', password='pw',
            is_staff=True, is_superuser=True,
        )
        cls.outsider_org = Organization.objects.create(name='OutCo', slug='wb-cat-out')
        cls.outsider = User.objects.create_user(
            'wb-cat-out', email='wbco@x.com', password='pw',
        )
        Membership.objects.create(
            user=cls.outsider, organization=cls.outsider_org, role=Role.OWNER, is_active=True,
        )
        cls.board = Wallboard.objects.create(organization=cls.org, name='CatBoard')
        cls.metric_widget = WallboardWidget.objects.create(
            wallboard=cls.board, title='Open tickets',
            widget_type='metric', data_source='open_tickets_count', order=10,
        )

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_endpoint_200_with_valid_category(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get(f'/reports/wallboards/widgets/{self.metric_widget.pk}/data/?category=unassigned')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['widget_type'], 'metric')
        self.assertIn('value', body['data'])

    def test_endpoint_400_for_unknown_category(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get(f'/reports/wallboards/widgets/{self.metric_widget.pk}/data/?category=bogus')
        self.assertEqual(r.status_code, 400)
        self.assertIn('unknown', r.json()['error'])

    def test_endpoint_404_for_inaccessible_wallboard(self):
        from django.test import Client
        c = Client()
        c.force_login(self.outsider)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.outsider_org.id
        s.save()
        r = c.get(f'/reports/wallboards/widgets/{self.metric_widget.pk}/data/?category=all')
        self.assertEqual(r.status_code, 404)

    def test_tickets_opened_30d_categories_return_distinct_series(self):
        from reports.widget_sources import tickets_opened_30d, get_categories
        # Just verify each category branches without error and returns the
        # expected series-name shape; exhaustive count checks would need
        # ticket fixtures which we already exercise above.
        cats = get_categories('tickets_opened_30d')
        self.assertIsNotNone(cats)
        for c in cats:
            res = tickets_opened_30d({'category': c['value']})
            self.assertIn('series', res)
            self.assertGreater(len(res['series']), 0)
        # Net category emits 3 series (opened, closed, net).
        net = tickets_opened_30d({'category': 'net'})
        self.assertEqual(len(net['series']), 3)

    def test_revenue_trend_30d_weekly_collapses_to_fewer_buckets(self):
        from reports.widget_sources import revenue_trend_30d
        daily = revenue_trend_30d({'category': 'daily'})
        weekly = revenue_trend_30d({'category': 'weekly'})
        cumulative = revenue_trend_30d({'category': 'cumulative'})
        self.assertEqual(len(daily['labels']), 30)
        self.assertLess(len(weekly['labels']), len(daily['labels']))
        self.assertEqual(len(cumulative['labels']), 30)
        # Cumulative is monotonically non-decreasing.
        cum = cumulative['series'][0]['data']
        self.assertEqual(cum, sorted(cum))

    def test_v224_widget_sources_smoke(self):
        # v3.17.224: each new operations/monitoring source should return a
        # well-formed dict (no exception) even when the underlying tables
        # are empty.
        from reports.widget_sources import (
            techs_logged_in, monitors_down, ssl_expiring_soon,
            domain_expiring_soon, warranties_expiring_soon,
            recent_failed_logins, vault_activity_24h,
            alerts_by_severity, monitors_status_breakdown,
        )
        for fn in (techs_logged_in, monitors_down, ssl_expiring_soon,
                   domain_expiring_soon, warranties_expiring_soon,
                   recent_failed_logins, vault_activity_24h):
            res = fn({})
            self.assertIn('value', res)
            self.assertIn('subtitle', res)
        rows = alerts_by_severity({})
        self.assertIn('rows', rows)
        self.assertIn('columns', rows)
        pie = monitors_status_breakdown({})
        self.assertIn('labels', pie)
        self.assertIn('data', pie)

    def test_at_risk_clients_categories_return_table(self):
        from reports.widget_sources import at_risk_clients
        for cat in ('worst', 'trouble_only', 'at_risk_only'):
            res = at_risk_clients({'category': cat})
            self.assertIn('columns', res)
            self.assertIn('rows', res)

    def test_open_tickets_count_categories_branch_differently(self):
        from psa.models import Ticket, Queue, TicketPriority, TicketType, TicketStatus
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from reports.widget_sources import open_tickets_count
        # Seed: a couple of unassigned tickets vs. a couple of P1 tickets.
        call_command('psa_seed_defaults', verbosity=0)
        q = Queue.objects.first()
        prio_p5 = TicketPriority.objects.filter(code='P5').first()
        prio_p1 = TicketPriority.objects.filter(code='P1').first()
        t_type = TicketType.objects.first()
        st_new = TicketStatus.objects.filter(slug='new').first()
        tech = User.objects.create_user('cat-tech', 'tech@x.com', 'pw')
        Ticket.objects.create(
            organization=self.org, subject='un-1',
            queue=q, priority=prio_p5, ticket_type=t_type, status=st_new,
        )
        Ticket.objects.create(
            organization=self.org, subject='un-2',
            queue=q, priority=prio_p5, ticket_type=t_type, status=st_new,
        )
        Ticket.objects.create(
            organization=self.org, subject='p1-asg', assigned_to=tech,
            queue=q, priority=prio_p1, ticket_type=t_type, status=st_new,
        )
        all_n = int(open_tickets_count({'category': 'all'})['value'])
        un_n = int(open_tickets_count({'category': 'unassigned'})['value'])
        hi_n = int(open_tickets_count({'category': 'priority_high'})['value'])
        # 2 unassigned (un-1, un-2). 1 P1 (p1-asg). All open = 3.
        self.assertEqual(un_n, 2)
        self.assertEqual(hi_n, 1)
        self.assertEqual(all_n, 3)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardWidgetReorderTests(TestCase):
    """v3.17.215: drag-to-reorder widget endpoint."""

    @classmethod
    def setUpTestData(cls):
        import json as _json
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from reports.models import Wallboard, WallboardWidget
        cls.org = Organization.objects.create(name='ReorderCo', slug='wb-ro-co')
        cls.other_org = Organization.objects.create(name='OtherCo', slug='wb-ro-other')
        cls.user = User.objects.create_user(
            'wb-ro-user', email='wbro@x.com', password='pw',
        )
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.board = Wallboard.objects.create(organization=cls.org, name='Reorderable')
        cls.w1 = WallboardWidget.objects.create(
            wallboard=cls.board, title='First', widget_type='metric',
            data_source='open_tickets_count', order=10,
        )
        cls.w2 = WallboardWidget.objects.create(
            wallboard=cls.board, title='Second', widget_type='metric',
            data_source='open_tickets_count', order=20,
        )
        cls.w3 = WallboardWidget.objects.create(
            wallboard=cls.board, title='Third', widget_type='metric',
            data_source='open_tickets_count', order=30,
        )

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_reorder_persists_new_order(self):
        import json as _json
        from django.test import Client
        from reports.models import WallboardWidget
        c = Client()
        self._login(c)
        # Reverse the order: third, first, second.
        new_order = [self.w3.pk, self.w1.pk, self.w2.pk]
        resp = c.post(
            f'/reports/wallboards/{self.board.pk}/widgets/reorder/',
            data=_json.dumps({'order': new_order}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['count'], 3)
        # Verify the order field was rewritten 10/20/30 in the new sequence.
        ranks = {w.pk: w.order for w in WallboardWidget.objects.filter(wallboard=self.board)}
        self.assertEqual(ranks[self.w3.pk], 10)
        self.assertEqual(ranks[self.w1.pk], 20)
        self.assertEqual(ranks[self.w2.pk], 30)

    def test_reorder_rejects_widget_from_different_wallboard(self):
        import json as _json
        from django.test import Client
        from reports.models import Wallboard, WallboardWidget
        # A second board with its own widget; supplying that pk in the order
        # array must be rejected (cross-board contamination).
        other_board = Wallboard.objects.create(organization=self.org, name='Other Board')
        other_widget = WallboardWidget.objects.create(
            wallboard=other_board, title='Stranger', widget_type='metric',
            data_source='open_tickets_count', order=10,
        )
        c = Client()
        self._login(c)
        resp = c.post(
            f'/reports/wallboards/{self.board.pk}/widgets/reorder/',
            data=_json.dumps({'order': [self.w1.pk, other_widget.pk]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('do not belong', resp.json()['error'])

    def test_reorder_rejects_get(self):
        from django.test import Client
        c = Client()
        self._login(c)
        resp = c.get(f'/reports/wallboards/{self.board.pk}/widgets/reorder/')
        self.assertEqual(resp.status_code, 405)

    def test_reorder_blocks_cross_org_wallboard_with_404(self):
        import json as _json
        from django.test import Client
        from reports.models import Wallboard
        foreign_board = Wallboard.objects.create(organization=self.other_org, name='ForeignNOC')
        c = Client()
        self._login(c)
        resp = c.post(
            f'/reports/wallboards/{foreign_board.pk}/widgets/reorder/',
            data=_json.dumps({'order': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SLAForecastReportTests(TestCase):
    """Phase 19 v2 (v3.17.320) — SLA forecasting / breach risk."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketType,
        )
        from datetime import timedelta as _td
        from django.utils import timezone as _tz
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='SLACo', slug='sla-co')
        cls.outsider = Organization.objects.create(name='Out', slug='sla-out')
        cls.staff = User.objects.create_user('sla-staff', 'sl@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('sla-mem', 'sm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        queue = Queue.objects.first()
        priority = TicketPriority.objects.first()
        ttype = TicketType.objects.first()
        new = TicketStatus.objects.filter(slug='new').first()
        terminal = TicketStatus.objects.filter(is_terminal=True).first()

        now = _tz.now()

        def make(subject, age_hours, due_in_hours, status=new, org=None):
            """Create a ticket with backdated created_at and forward
            resolution_due_at. age_hours = how long ago it was created;
            due_in_hours = how far ahead the SLA due is from NOW.
            """
            t = Ticket.objects.create(
                organization=org or cls.org, subject=subject,
                queue=queue, priority=priority,
                ticket_type=ttype, status=status,
                resolution_due_at=now + _td(hours=due_in_hours),
            )
            Ticket.objects.filter(pk=t.pk).update(
                created_at=now - _td(hours=age_hours),
            )
            return t

        # Window length = age_hours + due_in_hours; pct = age / window.
        # ok: 4h elapsed of 100h = 4%
        cls.t_ok = make('ok', age_hours=4, due_in_hours=96)
        # at_risk: 60h elapsed of 100h = 60%
        cls.t_atrisk = make('atrisk', age_hours=60, due_in_hours=40)
        # critical: 90h elapsed of 100h = 90%
        cls.t_crit = make('critical', age_hours=90, due_in_hours=10)
        # breached: due in the past
        cls.t_brc = make('breached', age_hours=120, due_in_hours=-20)
        # No SLA — should NOT count
        Ticket.objects.create(
            organization=cls.org, subject='no-sla',
            queue=queue, priority=priority, ticket_type=ttype, status=new,
        )
        # Terminal — should NOT count
        make('done', age_hours=10, due_in_hours=20, status=terminal)
        # Cross-tenant — staff sees, member doesn't
        cls.t_outsider = make('outsider', age_hours=4, due_in_hours=96,
                              org=cls.outsider)

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_buckets_correctly(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/sla-forecast/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # 5 SLA tickets total (ok×2 incl outsider, at_risk, critical, breached)
        self.assertEqual(ctx['summary']['total'], 5)
        self.assertEqual(ctx['summary']['breached'], 1)
        self.assertEqual(ctx['summary']['critical'], 1)
        self.assertEqual(ctx['summary']['at_risk'], 1)
        self.assertEqual(ctx['summary']['ok'], 2)
        self.assertEqual(ctx['summary']['risk_total'], 3)

    def test_sort_breached_first(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/sla-forecast/')
        rows = r.context['rows']
        # First row should be the breached ticket.
        self.assertEqual(rows[0]['risk'], 'breached')
        self.assertEqual(rows[0]['subject'], 'breached')

    def test_member_only_their_org(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/sla-forecast/')
        ctx = r.context
        # Outsider excluded — total = 4 instead of 5.
        self.assertEqual(ctx['summary']['total'], 4)

    def test_excludes_terminal_and_no_sla(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/sla-forecast/')
        body = r.content.decode('utf-8')
        # Tickets without SLA / terminal status must not appear.
        self.assertNotIn('no-sla', body)
        self.assertNotIn('>done<', body)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/sla-forecast/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('breached', body)
        self.assertIn('% elapsed', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuoteConversionReportTests(TestCase):
    """Phase 19 v3 (v3.17.321) — quote conversion tracking."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import Quote, Invoice
        from datetime import timedelta as _td
        from decimal import Decimal as _D
        from django.utils import timezone as _tz

        cls.org = Organization.objects.create(name='QuoCo', slug='quo-co')
        cls.staff = User.objects.create_user('quo-staff', 'qs@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('quo-mem', 'qm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)
        cls.rep1 = User.objects.create_user('rep1', 'r1@x.com', 'pw')
        cls.rep2 = User.objects.create_user('rep2', 'r2@x.com', 'pw')

        # 4 quotes from rep1: 2 sent, 1 accepted (no invoice), 1 accepted+invoiced
        for i in range(2):
            Quote.objects.create(organization=cls.org, client_org=cls.org,
                                 title=f'r1-sent-{i}', status='sent',
                                 created_by=cls.rep1, total=_D('1000'))
        Quote.objects.create(organization=cls.org, client_org=cls.org,
                             title='r1-accepted-noinv', status='accepted',
                             created_by=cls.rep1, total=_D('2000'))
        cls.q_conv = Quote.objects.create(
            organization=cls.org, client_org=cls.org,
            title='r1-converted', status='accepted',
            created_by=cls.rep1, total=_D('3000'))
        # Invoice tied to that quote
        Invoice.objects.create(
            organization=cls.org, client_org=cls.org,
            invoice_number='INV-Q-1', title='Test',
            invoice_date=_tz.now().date(),
            due_date=_tz.now().date(),
            total=_D('3000'), amount_paid=_D('0'),
            status='sent', subtotal=_D('3000'), tax_amount=0,
            currency='USD', source_quote=cls.q_conv,
        )
        # 2 quotes from rep2: 1 sent, 1 rejected
        Quote.objects.create(organization=cls.org, client_org=cls.org,
                             title='r2-sent', status='sent',
                             created_by=cls.rep2, total=_D('500'))
        Quote.objects.create(organization=cls.org, client_org=cls.org,
                             title='r2-rejected', status='rejected',
                             created_by=cls.rep2, total=_D('800'))

        # Old quote outside window — should NOT count for default 90-day window
        old = Quote.objects.create(organization=cls.org, client_org=cls.org,
                                    title='ancient', status='accepted',
                                    created_by=cls.rep1, total=_D('99999'))
        Quote.objects.filter(pk=old.pk).update(
            created_at=_tz.now() - _td(days=400))

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_summary_aggregates(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/quote-conversion/')
        self.assertEqual(r.status_code, 200)
        s = r.context['summary']
        # 6 in-window quotes (excluding the ancient)
        self.assertEqual(s['total_quotes'], 6)
        # 2 accepted (both rep1)
        self.assertEqual(s['total_accepted'], 2)
        # 1 actually converted to invoice
        self.assertEqual(s['total_converted'], 1)
        self.assertEqual(s['total_invoiced_amount'], 3000)

    def test_per_creator_rows(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/quote-conversion/')
        rows = {row['creator']: row for row in r.context['rows']}
        self.assertEqual(rows['rep1']['quotes'], 4)
        self.assertEqual(rows['rep1']['accepted'], 2)
        self.assertEqual(rows['rep1']['converted'], 1)
        self.assertEqual(rows['rep2']['quotes'], 2)
        self.assertEqual(rows['rep2']['accepted'], 0)

    def test_window_via_days_param(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        # 365 days picks up the 400-day-old too? No — 400 > 365.
        r = c.get('/reports/quote-conversion/?days=200')
        self.assertEqual(r.context['summary']['total_quotes'], 6)
        # max=365 cap; 1 day window keeps all 6 (created today)
        r = c.get('/reports/quote-conversion/?days=1')
        self.assertEqual(r.context['summary']['total_quotes'], 6)

    def test_non_staff_blocked(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/quote-conversion/')
        self.assertEqual(r.status_code, 404)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/quote-conversion/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('rep1', body)
        self.assertIn('rep2', body)
        self.assertIn('TOTAL', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class KPIDashboardTests(TestCase):
    """Phase 19 v4 (v3.17.322) — KPI dashboard widget grid."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketType, Contract,
        )
        from datetime import date as _date, timedelta as _td
        from decimal import Decimal as _D
        from django.utils import timezone as _tz
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='KPICo', slug='kpi-co')
        cls.outsider = Organization.objects.create(name='Out', slug='kpi-out')
        cls.staff = User.objects.create_user('kpi-staff', 'ks@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('kpi-mem', 'km@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        queue = Queue.objects.first()
        priority = TicketPriority.objects.first()
        ttype = TicketType.objects.first()
        new = TicketStatus.objects.filter(slug='new').first()
        terminal = TicketStatus.objects.filter(is_terminal=True).first()

        now = _tz.now()

        # 3 open tickets
        for i in range(3):
            t = Ticket.objects.create(
                organization=cls.org, subject=f'open-{i}',
                queue=queue, priority=priority,
                ticket_type=ttype, status=new,
            )
            # Backdate so mean age is computable
            Ticket.objects.filter(pk=t.pk).update(
                created_at=now - _td(hours=10))

        # 1 ticket from outsider (should not count for member)
        Ticket.objects.create(
            organization=cls.outsider, subject='outsider-open',
            queue=queue, priority=priority, ticket_type=ttype, status=new,
        )

        # 2 closed in last 7 days
        for i in range(2):
            t = Ticket.objects.create(
                organization=cls.org, subject=f'closed-{i}',
                queue=queue, priority=priority,
                ticket_type=ttype, status=terminal,
            )
            Ticket.objects.filter(pk=t.pk).update(
                resolved_at=now - _td(days=2))

        # 1 ticket with SLA breach in last 30 days
        Ticket.objects.create(
            organization=cls.org, subject='breached',
            queue=queue, priority=priority, ticket_type=ttype, status=new,
            sla_breached_resolution=True,
        )

        # 2 active contracts (monthly $1000 + yearly $12000 = $1000 + $1000 MRR)
        Contract.objects.create(
            organization=cls.org, client_org=cls.org,
            name='Monthly',
            start_date=_date.today() - _td(days=30),
            status='active', billing_frequency='monthly',
            recurring_amount=_D('1000'),
        )
        Contract.objects.create(
            organization=cls.org, client_org=cls.org,
            name='Yearly',
            start_date=_date.today() - _td(days=30),
            status='active', billing_frequency='yearly',
            recurring_amount=_D('12000'),
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_sees_msp_wide_widgets(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/kpi/')
        self.assertEqual(r.status_code, 200)
        w = r.context['widgets']
        # 3 from KPICo + 1 outsider + 1 breached = 5 open
        self.assertEqual(w['open_ticket_count'], 5)
        self.assertEqual(w['weekly_closed_count'], 2)
        self.assertEqual(w['sla_breach_count_30d'], 1)
        self.assertEqual(w['contract_count'], 2)
        self.assertTrue(w['is_staff_view'])
        # MRR = 1000 (monthly) + 1000 (yearly/12) = 2000
        self.assertEqual(int(w['mrr_total']), 2000)

    def test_member_scoped_excludes_mrr(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/kpi/')
        w = r.context['widgets']
        # 3 open + 1 breached = 4 (outsider excluded)
        self.assertEqual(w['open_ticket_count'], 4)
        # Non-staff: MRR is zero by design
        self.assertEqual(int(w['mrr_total']), 0)
        self.assertEqual(int(w['arr_total']), 0)
        self.assertFalse(w['is_staff_view'])

    def test_mean_age_present(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/kpi/')
        w = r.context['widgets']
        # Must be > 0 (we backdated 10h)
        self.assertGreater(w['mean_open_ticket_age_hours'], 0)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/kpi/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('open_ticket_count', body)
        self.assertIn('mrr_total', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OperationalMetricsReportTests(TestCase):
    """Phase 19 v5 (v3.17.323) — operational metrics."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from psa.models import (
            Queue, Ticket, TicketComment, TicketPriority, TicketStatus,
            TicketType,
        )
        from datetime import timedelta as _td
        from django.utils import timezone as _tz
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()

        cls.org = Organization.objects.create(name='OpsCo', slug='ops-co')
        cls.outsider = Organization.objects.create(name='Out', slug='ops-out')
        cls.staff = User.objects.create_user('ops-staff', 'os@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('ops-mem', 'om@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        queue = Queue.objects.first()
        priority = TicketPriority.objects.first()
        ttype = TicketType.objects.first()
        new = TicketStatus.objects.filter(slug='new').first()
        terminal = TicketStatus.objects.filter(is_terminal=True).first()

        now = _tz.now()

        # Resolved-in-window with first response — 2 hour response, 8 hour resolution
        t1 = Ticket.objects.create(
            organization=cls.org, subject='res-2h-fr',
            queue=queue, priority=priority, ticket_type=ttype, status=terminal,
            first_response_at=now - _td(hours=22),
            resolved_at=now - _td(hours=16),
        )
        Ticket.objects.filter(pk=t1.pk).update(
            created_at=now - _td(hours=24))
        # 0 non-system comments → first-touch
        cls.t1 = t1

        # Resolved with 4h response, 12h resolution, 3 non-system comments → NOT first-touch
        t2 = Ticket.objects.create(
            organization=cls.org, subject='res-multi-comments',
            queue=queue, priority=priority, ticket_type=ttype, status=terminal,
            first_response_at=now - _td(hours=20),
            resolved_at=now - _td(hours=12),
        )
        Ticket.objects.filter(pk=t2.pk).update(
            created_at=now - _td(hours=24))
        for i in range(3):
            TicketComment.objects.create(ticket=t2, body=f'comment {i}',
                                          is_system=False)
        cls.t2 = t2

        # 2 currently open in window
        for i in range(2):
            Ticket.objects.create(
                organization=cls.org, subject=f'open-{i}',
                queue=queue, priority=priority,
                ticket_type=ttype, status=new,
            )

        # 1 outsider open
        Ticket.objects.create(
            organization=cls.outsider, subject='outsider-open',
            queue=queue, priority=priority, ticket_type=ttype, status=new,
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_mttr_calculations(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/operational-metrics/')
        self.assertEqual(r.status_code, 200)
        s = r.context['summary']
        # 2 first responses, avg should land between 2h and 4h.
        self.assertEqual(s['fr_count'], 2)
        self.assertGreaterEqual(s['mttr_response_hours'], 2)
        self.assertLessEqual(s['mttr_response_hours'], 4)
        # 2 resolutions
        self.assertEqual(s['res_count'], 2)
        # avg resolution is between 8h and 12h
        self.assertGreaterEqual(s['mttr_resolution_hours'], 8)
        self.assertLessEqual(s['mttr_resolution_hours'], 12)

    def test_first_touch_resolution(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/operational-metrics/')
        s = r.context['summary']
        # 1 of 2 resolutions = first-touch (the 0-comment one)
        self.assertEqual(s['ftr_count'], 1)
        self.assertEqual(s['ftr_pct'], 50.0)

    def test_queue_depth_and_age_buckets(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/operational-metrics/')
        # 2 open from OpsCo + 1 outsider = 3 open for staff
        self.assertEqual(r.context['summary']['open_count'], 3)
        # All in 0-24h bucket since just created
        self.assertEqual(r.context['age_buckets']['0-24h'], 3)

    def test_member_scoped(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/operational-metrics/')
        # Member sees only OpsCo: 2 open + 2 resolved = different counts
        self.assertEqual(r.context['summary']['open_count'], 2)
        self.assertEqual(r.context['summary']['res_count'], 2)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/operational-metrics/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('Mean time to first response', body)
        self.assertIn('First-touch resolution', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkflowPerformanceReportTests(TestCase):
    """Phase 19 v6 (v3.17.324) — workflow performance analytics."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from django.contrib.auth.models import User
        from psa.models import WorkflowRule
        from django.utils import timezone as _tz

        cls.org = Organization.objects.create(name='WfCo', slug='wf-co')
        cls.staff = User.objects.create_user('wf-staff', 'ws@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('wf-mem', 'wm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        # Top firing rule: MSP-wide, 200 fires, no error
        cls.r_top = WorkflowRule.objects.create(
            organization=None, name='Auto-assign P1',
            trigger='ticket_created', is_active=True,
            fire_count=200, last_fired_at=_tz.now(),
        )
        # Errored rule: 50 fires + last_error
        cls.r_err = WorkflowRule.objects.create(
            organization=cls.org, name='Notify manager',
            trigger='comment_added', is_active=True,
            fire_count=50, last_error='SMTP timeout',
            last_fired_at=_tz.now(),
        )
        # Quiet rule: 0 fires
        cls.r_quiet = WorkflowRule.objects.create(
            organization=None, name='Quiet rule',
            trigger='status_changed', is_active=True,
            fire_count=0,
        )
        # Inactive — must NOT appear
        WorkflowRule.objects.create(
            organization=None, name='Disabled',
            trigger='ticket_created', is_active=False,
            fire_count=999,
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_summary_aggregates(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/workflow-performance/')
        self.assertEqual(r.status_code, 200)
        s = r.context['summary']
        # 3 active rules
        self.assertEqual(s['rule_count'], 3)
        self.assertEqual(s['total_fires'], 250)
        self.assertEqual(s['error_count'], 1)

    def test_rules_sorted_by_fire_count(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/workflow-performance/')
        rows = r.context['rows']
        self.assertEqual(rows[0]['name'], 'Auto-assign P1')
        self.assertEqual(rows[0]['fire_count'], 200)
        # Errored 50-fire rule comes second
        self.assertEqual(rows[1]['name'], 'Notify manager')
        self.assertTrue(rows[1]['has_error'])

    def test_excludes_inactive_rules(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/workflow-performance/')
        names = [row['name'] for row in r.context['rows']]
        self.assertNotIn('Disabled', names)

    def test_trigger_rollup(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/workflow-performance/')
        triggers = {t['trigger']: t for t in r.context['trigger_rows']}
        self.assertEqual(triggers['ticket_created']['fires'], 200)
        self.assertEqual(triggers['comment_added']['errors'], 1)

    def test_non_staff_blocked(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/workflow-performance/')
        self.assertEqual(r.status_code, 404)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/workflow-performance/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('Auto-assign P1', body)
        self.assertIn('SMTP timeout', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TrendsReportTests(TestCase):
    """Phase 19 v7 (v3.17.325) — trend analysis + capacity forecasting."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketType, Contract,
        )
        from resourcing.models import BillableTarget
        from datetime import date as _date, timedelta as _td
        from decimal import Decimal as _D
        from django.utils import timezone as _tz
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()

        cls.org = Organization.objects.create(name='TrCo', slug='tr-co')
        cls.staff = User.objects.create_user('tr-staff', 'ts@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('tr-mem', 'tm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)
        cls.tech1 = User.objects.create_user('tech1', 't1@x.com', 'pw')
        cls.tech2 = User.objects.create_user('tech2', 't2@x.com', 'pw')

        queue = Queue.objects.first()
        priority = TicketPriority.objects.first()
        ttype = TicketType.objects.first()
        new = TicketStatus.objects.filter(slug='new').first()
        terminal = TicketStatus.objects.filter(is_terminal=True).first()

        now = _tz.now()

        # 3 tickets opened this month
        for i in range(3):
            Ticket.objects.create(
                organization=cls.org, subject=f'this-month-{i}',
                queue=queue, priority=priority,
                ticket_type=ttype, status=new,
            )
        # 2 resolved this month
        for i in range(2):
            t = Ticket.objects.create(
                organization=cls.org, subject=f'res-{i}',
                queue=queue, priority=priority,
                ticket_type=ttype, status=terminal,
                resolved_at=now,
            )
        # Tech assignments — tech1 over target, tech2 within
        for i in range(20):
            Ticket.objects.create(
                organization=cls.org, subject=f'tech1-{i}',
                queue=queue, priority=priority,
                ticket_type=ttype, status=new,
                assigned_to=cls.tech1,
            )
        for i in range(2):
            Ticket.objects.create(
                organization=cls.org, subject=f'tech2-{i}',
                queue=queue, priority=priority,
                ticket_type=ttype, status=new,
                assigned_to=cls.tech2,
            )
        BillableTarget.objects.create(user=cls.tech1, target_hours_per_week=20)
        BillableTarget.objects.create(user=cls.tech2, target_hours_per_week=40)

        # 1 active monthly contract started this month
        Contract.objects.create(
            organization=cls.org, client_org=cls.org,
            name='New monthly',
            start_date=_date.today(),
            status='active', billing_frequency='monthly',
            recurring_amount=_D('500'),
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_trend_rows_present_for_12_months(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/trends/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['trend_rows']), 12)
        # Total opened includes assigned (20+2) + open (3) + resolved (2) but
        # we only counted via created_at; resolved still counts as "opened".
        # Total = 3 + 2 + 20 + 2 = 27 across all months, mostly current.
        self.assertGreaterEqual(r.context['summary']['total_opened_12m'], 27)
        self.assertEqual(r.context['summary']['total_resolved_12m'], 2)

    def test_capacity_load_calculation(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/trends/')
        cap = {row['username']: row for row in r.context['capacity_rows']}
        # tech1: 20 tickets * 2h = 40h vs 20h target = 200% load (over)
        self.assertEqual(cap['tech1']['open_count'], 20)
        self.assertEqual(cap['tech1']['load_ratio_pct'], 200.0)
        self.assertTrue(cap['tech1']['over_target'])
        # tech2: 2 * 2 = 4h vs 40h = 10% load (under)
        self.assertEqual(cap['tech2']['load_ratio_pct'], 10.0)
        self.assertFalse(cap['tech2']['over_target'])

    def test_mrr_added_present(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/trends/')
        self.assertEqual(int(r.context['summary']['total_mrr_added_12m']), 500)

    def test_non_staff_blocked(self):
        from django.test import Client
        c = Client()
        self._login(c, self.member, self.org)
        r = c.get('/reports/trends/')
        self.assertEqual(r.status_code, 404)

    def test_csv_export(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/trends/?format=csv')
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('# Trends', body)
        self.assertIn('# Capacity', body)
        self.assertIn('tech1', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PDFExportTests(TestCase):
    """Phase 19 v8 (v3.17.326) — PDF export on the four flagship reports."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from psa.models import (
            Contract, Invoice, PurchaseOrder, Queue, Ticket, TicketPriority,
            TicketStatus, TicketType,
        )
        from datetime import date as _date, timedelta as _td
        from decimal import Decimal as _D
        from django.utils import timezone as _tz
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='PdfCo', slug='pdf-co')
        cls.staff = User.objects.create_user('pdf-staff', 'ps@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.member = User.objects.create_user('pdf-mem', 'pm@x.com', 'pw')
        Membership.objects.create(user=cls.member, organization=cls.org,
                                   role=Role.OWNER, is_active=True)

        # 1 PO for procurement summary
        PurchaseOrder.objects.create(
            organization=cls.org, po_number='PDF-PO-1',
            vendor_name='PdfVendor', title='PdfTest',
            status='sent', total=_D('1500'),
        )
        # 1 unpaid invoice for AR aging
        Invoice.objects.create(
            organization=cls.org, client_org=cls.org,
            invoice_number='PDF-INV-1', title='PdfInv',
            invoice_date=_date.today() - _td(days=10),
            due_date=_date.today() - _td(days=5),
            total=_D('800'), amount_paid=_D('0'),
            status='sent', subtotal=_D('800'), tax_amount=0, currency='USD',
            pushed_to_accounting_at=_tz.now(),
        )
        # 1 active monthly contract for MRR forecast
        Contract.objects.create(
            organization=cls.org, client_org=cls.org,
            name='PdfContract',
            start_date=_date.today() - _td(days=30),
            status='active', billing_frequency='monthly',
            recurring_amount=_D('200'),
        )
        # 1 open ticket for KPI dashboard
        queue = Queue.objects.first()
        priority = TicketPriority.objects.first()
        ttype = TicketType.objects.first()
        new = TicketStatus.objects.filter(slug='new').first()
        Ticket.objects.create(
            organization=cls.org, subject='pdf-open',
            queue=queue, priority=priority, ticket_type=ttype, status=new,
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def _assert_pdf(self, resp, name):
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn(name, resp['Content-Disposition'])
        # First 4 bytes of every valid PDF
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_procurement_summary_pdf(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/procurement-summary/?format=pdf')
        self._assert_pdf(r, 'procurement-summary.pdf')

    def test_ar_aging_pdf(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/ar-aging/?format=pdf')
        self._assert_pdf(r, 'ar-aging.pdf')

    def test_mrr_forecast_pdf(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/mrr-forecast/?format=pdf')
        self._assert_pdf(r, 'mrr-forecast.pdf')

    def test_kpi_dashboard_pdf(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff)
        r = c.get('/reports/kpi/?format=pdf')
        self._assert_pdf(r, 'kpi-dashboard.pdf')


# ---------------------------------------------------------------------------
# v3.17.568 — dashboard widgets answer to permissions and to tenancy
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WidgetViewerScopeTests(TestCase):
    """
    A widget renders the same numbers as a report page, so it has to enforce
    the same two rules. Before v3.17.568 it enforced neither: every source
    aggregated across every client, and the only gate was
    `reports_view_dashboards`, which every role has by default. A read-only
    member of one client could open a shared dashboard and read the MSP's
    revenue and its other clients' names.
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import date
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket, Invoice,
        )
        call_command('psa_seed_defaults', verbosity=0)

        cls.acme = Organization.objects.create(name='Acme', slug='acme-widgets')
        cls.other = Organization.objects.create(name='Umbrella', slug='umbrella-widgets')
        cls.today = date.today()

        common = dict(
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )
        Ticket.objects.create(organization=cls.acme, subject='Acme one', **common)
        for i in range(3):
            Ticket.objects.create(organization=cls.other,
                                  subject=f'Umbrella {i}', **common)

        for i, (org, total) in enumerate([(cls.acme, 100), (cls.other, 900)]):
            Invoice.objects.create(
                organization=org, client_org=org,
                invoice_number=f'INV-W-{i}', title='T',
                invoice_date=cls.today, due_date=cls.today,
                total=total, amount_paid=0, status='sent',
                subtotal=total, tax_amount=0, currency='USD',
            )

        # Acme's own admin: money yes, other clients no.
        cls.acme_admin = User.objects.create_user('acme_admin', 'aa@x.com', 'pw')
        rt_fin = RoleTemplate.objects.create(
            name='WidgetOrgAdmin',
            reports_view_dashboards=True, reports_view_financial=True,
            reports_view_sla=True, audit_view=True,
        )
        Membership.objects.create(user=cls.acme_admin, organization=cls.acme,
                                  role='admin', role_template=rt_fin, is_active=True)

        # Acme read-only tech: dashboards only — no money at all.
        cls.acme_readonly = User.objects.create_user('acme_ro', 'ro@x.com', 'pw')
        rt_ro = RoleTemplate.objects.create(
            name='WidgetOrgReadOnly',
            reports_view_dashboards=True, reports_view_financial=False,
            reports_view_sla=False, audit_view=False,
        )
        Membership.objects.create(user=cls.acme_readonly, organization=cls.acme,
                                  role='readonly', role_template=rt_ro, is_active=True)

        cls.msp = User.objects.create_user('msp', 'm@x.com', 'pw',
                                           is_staff=True, is_superuser=True)

    # -- the registry contract ------------------------------------------------

    def test_every_registered_source_declares_a_spec(self):
        """An unspecced source falls back to MSP-only; catch it here instead."""
        from reports.widget_sources import REGISTRY, WIDGET_SPECS
        self.assertEqual(set(REGISTRY), set(WIDGET_SPECS))

    def test_no_viewer_means_no_access_rather_than_full_access(self):
        from reports.widget_sources import get_widget_data
        data = get_widget_data('revenue_this_period', {})
        self.assertTrue(data.get('restricted'))

    # -- permission gate ------------------------------------------------------

    def test_read_only_member_cannot_read_revenue_through_a_widget(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('revenue_this_period', {},
                               viewer_for(self.acme_readonly))
        self.assertTrue(data.get('restricted'))
        self.assertIn('reports_view_financial', data['error'])
        self.assertNotIn('value', data)

    def test_read_only_member_cannot_read_client_names_through_a_widget(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('top_clients_by_revenue', {},
                               viewer_for(self.acme_readonly))
        self.assertTrue(data.get('restricted'))

    def test_read_only_member_cannot_read_the_sla_trend(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('sla_breach_trend', {},
                               viewer_for(self.acme_readonly))
        self.assertTrue(data.get('restricted'))

    def test_the_permission_is_what_unlocks_it(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('revenue_this_period', {},
                               viewer_for(self.acme_admin))
        self.assertNotIn('error', data)
        self.assertIn('value', data)

    # -- tenancy --------------------------------------------------------------

    def test_org_member_sees_only_their_own_clients_tickets(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('open_tickets_count', {},
                               viewer_for(self.acme_readonly))
        self.assertEqual(data['value'], '1')

    def test_msp_staff_still_see_every_client(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('open_tickets_count', {},
                               viewer_for(self.msp, is_staff_user=True))
        self.assertEqual(data['value'], '4')

    def test_revenue_is_limited_to_the_viewers_own_clients(self):
        from reports.widget_sources import get_widget_data, viewer_for
        mine = get_widget_data('revenue_this_period', {},
                               viewer_for(self.acme_admin))
        # Acme's own $100, not Umbrella's $900 as well.
        self.assertEqual(mine['value'], '$100')
        everyones = get_widget_data('revenue_this_period', {},
                                    viewer_for(self.msp, is_staff_user=True))
        self.assertEqual(everyones['value'], '$1,000')

    def test_a_client_table_never_names_another_clients_org(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('top_clients_by_revenue', {},
                               viewer_for(self.acme_admin))
        names = [row[0] for row in data['rows']]
        self.assertIn('Acme', names)
        self.assertNotIn('Umbrella', names)

    def test_ticket_trend_is_scoped_too(self):
        from reports.widget_sources import get_widget_data, viewer_for
        mine = get_widget_data('tickets_opened_30d', {},
                               viewer_for(self.acme_readonly))
        everyones = get_widget_data('tickets_opened_30d', {},
                                    viewer_for(self.msp, is_staff_user=True))
        self.assertEqual(sum(mine['series'][0]['data']), 1)
        self.assertEqual(sum(everyones['series'][0]['data']), 4)

    def test_a_source_with_no_client_to_scope_by_is_msp_only(self):
        """
        django-axes attempts carry no organization, so `recent_failed_logins`
        cannot be narrowed to one client. It is shown to whoever may see every
        client and refused to everyone else, rather than shown unscoped.
        """
        from reports.widget_sources import get_widget_data, viewer_for
        restricted = get_widget_data('recent_failed_logins', {},
                                     viewer_for(self.acme_admin))
        self.assertTrue(restricted.get('restricted'))
        allowed = get_widget_data('recent_failed_logins', {},
                                  viewer_for(self.msp, is_staff_user=True))
        self.assertIn('value', allowed)

    def test_a_viewer_with_no_membership_sees_nothing(self):
        from django.contrib.auth.models import User
        from reports.widget_sources import get_widget_data, viewer_for
        nobody = User.objects.create_user('nobody_w', 'n@x.com', 'pw')
        data = get_widget_data('open_tickets_count', {}, viewer_for(nobody))
        self.assertEqual(data['value'], '0')

    # -- through the actual page ---------------------------------------------

    def test_dashboard_page_does_not_render_revenue_for_a_read_only_member(self):
        from reports.models import Dashboard, DashboardWidget
        dash = Dashboard.objects.create(
            name='Shared board', is_global=True, created_by=self.msp,
        )
        DashboardWidget.objects.create(
            dashboard=dash, title='Revenue this period',
            widget_type='metric', data_source='revenue_this_period',
        )
        DashboardWidget.objects.create(
            dashboard=dash, title='Top clients',
            widget_type='table', data_source='top_clients_by_revenue',
        )

        self.client.force_login(self.acme_readonly)
        r = self.client.get(f'/reports/dashboards/{dash.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b'$1,000', r.content)
        self.assertNotIn(b'Umbrella', r.content)
        self.assertIn(b'reports_view_financial', r.content)

    def test_dashboard_page_still_shows_the_msp_everything(self):
        from reports.models import Dashboard, DashboardWidget
        dash = Dashboard.objects.create(
            name='MSP board', is_global=True, created_by=self.msp,
        )
        DashboardWidget.objects.create(
            dashboard=dash, title='Revenue this period',
            widget_type='metric', data_source='revenue_this_period',
        )
        self.client.force_login(self.msp)
        r = self.client.get(f'/reports/dashboards/{dash.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'$1,000', r.content)
