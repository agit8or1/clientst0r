"""Business Overview (executive dashboard).

Pins, for every metric: the value from seeded data, that the drill-down is
exactly the records behind it, the not-configured state when its source is
missing (never a zero), completeness flags, filters, permission gating, and
tenant isolation (a technician scoped to one customer never sees another's
numbers or records). Metrics whose reporting functions arrive with other
branches are exercised through stand-ins with the documented return shapes.
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from executive import metrics, providers
from executive.metrics import Filters

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _make_msp_tech(user, global_role=None):
    from accounts.models import UserProfile, UserType
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = global_role
    profile.save()
    return user


def _filters(**kw):
    today = timezone.localdate()
    params = {'start': (today - timedelta(days=60)).isoformat(), 'end': today.isoformat()}
    params.update({k: str(v) for k, v in kw.items()})
    return Filters.from_query(params)


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization, SystemSetting
        from locations.models import Location
        from psa.models import Queue, TicketPriority, TicketStatus, TicketType

        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()

        cls.a = Organization.objects.create(name='Alpha Exec', slug='alpha-exec')
        cls.b = Organization.objects.create(name='Bravo Exec', slug='bravo-exec')
        cls.loc_a = Location.objects.create(organization=cls.a, name='Alpha HQ')
        cls.today = timezone.localdate()
        cls.now = timezone.now()

        cls.su = User.objects.create_user('ex_su', 'su@x.com', 'pw', is_superuser=True, is_staff=True)
        cls.owner_role = RoleTemplate.objects.create(
            name='Exec owner', organization=None, reports_view_dashboards=True,
            reports_view_financial=True, reports_view_sla=True, reports_view_capacity=True,
            billing_view_aging=True, billing_view_invoices=True, tickets_view=True, procurement_view=True,
            security_alerts_view=True, view_profitability=True)
        # Revenue but not cost: view_profitability gates cost and margin.
        cls.fin_role = RoleTemplate.objects.create(
            name='Exec finance', organization=None, reports_view_dashboards=True,
            reports_view_financial=True, view_profitability=False)
        cls.l1_role = RoleTemplate.objects.create(
            name='Exec L1', organization=None, reports_view_dashboards=True, tickets_view=True,
            reports_view_financial=False, security_alerts_view=False)
        cls.scoped = _make_msp_tech(User.objects.create_user('ex_scoped', 's@x.com', 'pw'), cls.owner_role)
        cls.scoped.profile.client_scope = 'selected'
        cls.scoped.profile.save()
        cls.scoped.profile.scope_organizations.set([cls.a])
        cls.fin = _make_msp_tech(User.objects.create_user('ex_fin', 'f@x.com', 'pw'), cls.fin_role)
        cls.l1 = _make_msp_tech(User.objects.create_user('ex_l1', 'l1@x.com', 'pw'), cls.l1_role)
        cls.customer = User.objects.create_user('ex_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=cls.customer, organization=cls.a, role='owner', is_active=True)

        cls.status_open = TicketStatus.objects.filter(is_terminal=False).first()
        cls.status_closed = TicketStatus.objects.filter(is_terminal=True).first()
        cls.p1 = TicketPriority.objects.get(code='P1')
        cls.p3 = TicketPriority.objects.get(code='P3')
        cls.ttype = TicketType.objects.first()
        cls.queue = Queue.objects.first()

    def setUp(self):
        cache.clear()

    def ticket(self, org, subject, priority=None, status=None, **kw):
        from psa.models import Ticket
        return Ticket.objects.create(organization=org, subject=subject, status=status or self.status_open,
                                     priority=priority or self.p3, ticket_type=self.ttype, queue=self.queue,
                                     **kw)

    def run_metric(self, key, user=None, **filters):
        return metrics.compute(providers.get(key), user or self.su, _filters(**filters), use_cache=False)

    def rows(self, key, user=None, part='', **filters):
        _r, _c, rows, _cap = metrics.drilldown(providers.get(key), user or self.su, _filters(**filters),
                                               part=part, use_cache=False)
        return rows


# -- revenue / billing ---------------------------------------------------------

class RevenueTests(Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from psa.models import Contract, Invoice
        cls.contract = Contract.objects.create(organization=cls.a, client_org=cls.a, name='Alpha MSA',
                                               contract_type='managed_services', status='active',
                                               start_date=cls.today - timedelta(days=400))
        d = cls.today - timedelta(days=5)
        cls.i1 = Invoice.objects.create(organization=cls.a, client_org=cls.a, title='i1', invoice_date=d,
                                        status='sent', total=Decimal('100'), source_contract=cls.contract)
        cls.i2 = Invoice.objects.create(organization=cls.a, client_org=cls.a, title='i2', invoice_date=d,
                                        status='paid', total=Decimal('200'), amount_paid=Decimal('200'))
        cls.draft = Invoice.objects.create(organization=cls.a, client_org=cls.a, title='draft', invoice_date=d,
                                           status='draft', total=Decimal('999'))
        Invoice.objects.create(organization=cls.a, client_org=cls.a, title='void', invoice_date=d,
                               status='void', total=Decimal('999'))
        Invoice.objects.create(organization=cls.a, client_org=cls.a, title='old',
                               invoice_date=cls.today - timedelta(days=400), status='paid', total=Decimal('7'),
                               amount_paid=Decimal('7'))
        cls.ib = Invoice.objects.create(organization=cls.b, client_org=cls.b, title='ib', invoice_date=d,
                                        status='overdue', total=Decimal('50'),
                                        due_date=cls.today - timedelta(days=45))

    def test_revenue_value_and_drilldown(self):
        r = self.run_metric('revenue_trend')
        self.assertEqual(r.state, 'ok')
        self.assertEqual(r.value, Decimal('350.00'))
        ids = {row['id'] for row in self.rows('revenue_trend')}
        self.assertEqual(ids, {self.i1.pk, self.i2.pk, self.ib.pk})
        self.assertEqual(sum(t['value'] for t in r.trend), Decimal('350.00'))

    def test_revenue_customer_and_service_line_filters(self):
        self.assertEqual(self.run_metric('revenue_trend', customer=self.a.pk).value, Decimal('300.00'))
        r = self.run_metric('revenue_trend', service_line='managed_services')
        self.assertEqual(r.value, Decimal('100.00'))
        self.assertEqual([x['id'] for x in self.rows('revenue_trend', service_line='managed_services')],
                         [self.i1.pk])

    def test_accounts_receivable_follows_the_aging_report(self):
        from psa.models import get_psa_balance
        r = self.run_metric('accounts_receivable')
        expected = get_psa_balance(self.a)['outstanding'] + get_psa_balance(self.b)['outstanding']
        self.assertEqual(r.value, expected)
        # get_psa_balance counts every non-void invoice with a balance.
        self.assertEqual(r.value, Decimal('1149.00'))
        buckets = {b['label']: b['value'] for b in r.breakdown}
        self.assertEqual(buckets['31–60 days'], Decimal('50.00'))
        self.assertEqual(buckets['0–30 days'], Decimal('1099.00'))
        rows = self.rows('accounts_receivable')
        self.assertEqual({x['id'] for x in rows}, {self.i1.pk, self.draft.pk, self.ib.pk})
        self.assertEqual(sum(Decimal(str(x['balance'])) for x in rows), r.value)
        self.assertIn('no accounting sync', r.source)

    def test_accounts_receivable_labels_synced_status(self):
        self.i1.provider_synced_at = timezone.now()
        self.i1.save(update_fields=['provider_synced_at'])
        r = self.run_metric('accounts_receivable')
        self.assertIn('synced from the accounting provider for 1 of 3', r.source)

    def test_service_line_is_ignored_by_ar(self):
        r = self.run_metric('accounts_receivable', service_line='retainer')
        self.assertIn('service_line', r.ignored_filters)
        self.assertEqual(r.value, Decimal('1149.00'))
        self.assertEqual(self.run_metric('accounts_receivable', user=self.scoped).value, Decimal('1099.00'))

    def test_revenue_matches_report_function(self):
        from reports.queries import revenue_by_client
        start, end = _filters().start, _filters().end
        self.assertEqual(self.run_metric('revenue_trend').value,
                         Decimal(str(sum(r['invoiced'] for r in revenue_by_client(start, end)))).quantize(Decimal('0.01')))

    def test_outstanding_quotes(self):
        from psa.models import Quote
        q1 = Quote.objects.create(organization=self.a, client_org=self.a, title='q1', status='sent',
                                  total=Decimal('500'))
        Quote.objects.filter(pk=q1.pk).update(sent_at=self.now - timedelta(days=40))
        Quote.objects.create(organization=self.a, client_org=self.a, title='draft', status='draft',
                             total=Decimal('9'))
        q2 = Quote.objects.create(organization=self.b, client_org=self.b, title='q2', status='sent',
                                  total=Decimal('20'), sent_at=self.now)
        r = self.run_metric('outstanding_quotes')
        self.assertEqual(r.value, Decimal('520.00'))
        aging = {b['label']: b for b in r.breakdown}
        self.assertEqual(aging['31–60 days']['count'], 1)
        self.assertEqual(aging['0–7 days']['count'], 1)
        self.assertEqual({x['id'] for x in self.rows('outstanding_quotes')}, {q1.pk, q2.pk})


class ContractTests(Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from psa.models import Contract
        mk = lambda org, name, days, **kw: Contract.objects.create(  # noqa: E731
            organization=org, client_org=org, name=name, status=kw.pop('status', 'active'),
            contract_type=kw.pop('contract_type', 'retainer'),
            start_date=kw.pop('start', cls.today - timedelta(days=300)),
            end_date=None if days is None else cls.today + timedelta(days=days), **kw)
        cls.c10 = mk(cls.a, 'ends 10', 10, auto_renew=True)
        cls.c45 = mk(cls.b, 'ends 45', 45, contract_type='managed_services')
        cls.c120 = mk(cls.a, 'ends 120', 120)
        cls.cnew = mk(cls.b, 'new open', None, start=cls.today - timedelta(days=10))
        mk(cls.a, 'draft', 5, status='draft')

    def test_renewals_windows(self):
        r = self.run_metric('contract_renewals')
        self.assertEqual(r.value, 2)
        w = {b['label']: b['value'] for b in r.breakdown}
        self.assertEqual((w['30 days'], w['60 days'], w['90 days']), (1, 2, 2))
        self.assertEqual([x['id'] for x in self.rows('contract_renewals')], [self.c10.pk, self.c45.pk])
        # No recurring amounts: MRR at stake is flagged, not presented as complete.
        self.assertFalse(r.is_complete)
        self.assertIn('2 contracts have no recurring amount', r.unknown_reason)
        self.assertEqual(self.run_metric('contract_renewals', customer=self.a.pk).value, 1)
        self.assertIn('service_line', self.run_metric('contract_renewals', service_line='retainer').ignored_filters)

    def test_customer_growth(self):
        r = self.run_metric('customer_growth')
        self.assertEqual(r.value, 2)
        self.assertEqual({x['id'] for x in self.rows('customer_growth')}, {self.a.pk, self.b.pk})
        b = {x['label']: x['value'] for x in r.breakdown}
        self.assertEqual(b['New customers in period'], 0)  # Bravo's first contract started 300 days ago
        self.assertEqual(b['Churned contracts'], 0)
        self.assertTrue(r.is_complete)
        self.assertEqual(self.run_metric('customer_growth', service_line='managed_services').value, 1)

    def test_customer_growth_flags_undated_cancellation(self):
        from psa.models import Contract
        Contract.objects.create(organization=self.a, client_org=self.a, name='gone', status='cancelled',
                                start_date=self.today - timedelta(days=100))
        r = self.run_metric('customer_growth')
        self.assertFalse(r.is_complete)
        self.assertIn('cancellations have no end date', r.unknown_reason)

    def test_customer_growth_passes_scope_to_churn(self):
        from reports import queries as rq
        real = rq.contract_churn
        with mock.patch('reports.queries.contract_churn', side_effect=real) as fn:
            r = self.run_metric('customer_growth', user=self.scoped)
        self.assertEqual(fn.call_args[0][2], [self.a.pk])
        self.assertEqual(r.value, 1)

    def test_mrr_from_recurring_revenue(self):
        from psa.models import Contract
        Contract.objects.filter(pk=self.c120.pk).update(billing_frequency='monthly', recurring_amount=Decimal('900'))
        Contract.objects.filter(pk=self.cnew.pk).update(billing_frequency='quarterly', recurring_amount=Decimal('300'))
        r = self.run_metric('mrr_arr')
        self.assertEqual(r.value, 1000.0)
        self.assertEqual(r.breakdown[0], {'label': 'ARR', 'value': 12000.0, 'unit': 'currency'})
        self.assertEqual({x['contract_id'] for x in self.rows('mrr_arr')}, {self.c120.pk, self.cnew.pk})
        self.assertEqual(self.run_metric('mrr_arr', user=self.scoped).value, 900.0)
        self.assertTrue(any('no recurring amount' in n for n in r.notes))


# -- delegated metrics (reports.queries functions from dev/profitability) ------

class ProfitabilityTests(Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from psa.models import Invoice, TicketTimeEntry
        from resourcing.models import TechCostRate
        d = cls.today - timedelta(days=3)
        Invoice.objects.create(organization=cls.a, client_org=cls.a, title='a', invoice_date=d,
                               status='sent', total=Decimal('1000'))
        Invoice.objects.create(organization=cls.b, client_org=cls.b, title='b', invoice_date=d,
                               status='sent', total=Decimal('500'))
        cls.rated = _make_msp_tech(User.objects.create_user('ex_rated', 'r@x.com', 'pw'))
        cls.unrated = _make_msp_tech(User.objects.create_user('ex_unrated', 'u@x.com', 'pw'))
        TechCostRate.objects.create(user=cls.rated, rate_per_hour=Decimal('50'),
                                    effective_from=cls.today - timedelta(days=365))
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        base = dict(status=TicketStatus.objects.filter(is_terminal=False).first(),
                    priority=TicketPriority.objects.get(code='P3'), ticket_type=TicketType.objects.first(),
                    queue=Queue.objects.first())
        ta = Ticket.objects.create(organization=cls.a, subject='a work', **base)
        tb = Ticket.objects.create(organization=cls.b, subject='b work', **base)
        start = timezone.now() - timedelta(days=3)
        TicketTimeEntry.objects.create(ticket=ta, user=cls.rated, started_at=start,
                                       ended_at=start + timedelta(hours=2), duration_minutes=120)
        TicketTimeEntry.objects.create(ticket=tb, user=cls.unrated, started_at=start,
                                       ended_at=start + timedelta(hours=12), duration_minutes=720)

    def test_gross_margin_unknown_when_hours_lack_a_cost_rate(self):
        r = self.run_metric('gross_margin')
        self.assertEqual(r.state, 'ok')
        self.assertIsNone(r.value)  # unknown, never a partial margin
        self.assertFalse(r.is_complete)
        self.assertEqual(r.unknown_reason, '12 hours without a cost rate')
        self.assertEqual(r.label, 'Operational estimate, not accounting results')
        self.assertEqual({x['client_id'] for x in self.rows('gross_margin')}, {self.a.pk, self.b.pk})

    def test_gross_margin_scoped_is_complete(self):
        r = self.run_metric('gross_margin', user=self.scoped)
        self.assertEqual(r.value, 90.0)  # (1000 - 2h x 50) / 1000
        self.assertTrue(r.is_complete)
        self.assertEqual([x['client_id'] for x in self.rows('gross_margin', user=self.scoped)], [self.a.pk])

    def test_margin_matches_profitability_report(self):
        from reports.costing import summarize
        from reports.queries import profitability_by_client
        f = _filters(customer=self.a.pk)
        expected = summarize(profitability_by_client(f.start, f.end, organization=[self.a.pk]))
        self.assertEqual(self.run_metric('gross_margin', customer=self.a.pk).value, expected['blended_margin_pct'])

    def test_customer_profitability_ranks_known_margins_only(self):
        r = self.run_metric('customer_profitability')
        self.assertEqual(r.value, 2)
        self.assertEqual([b['label'] for b in r.breakdown], ['Alpha Exec'])
        self.assertFalse(r.is_complete)
        self.assertIn('1 customers have an unknown margin', r.unknown_reason)

    def test_cost_cards_need_view_profitability(self):
        self.assertEqual(self.run_metric('revenue_trend', user=self.fin).state, 'ok')
        for key in ('gross_margin', 'customer_profitability'):
            r = self.run_metric(key, user=self.fin)
            self.assertEqual(r.state, 'forbidden', key)
            self.assertIsNone(r.value)

    def test_unbilled_time_without_bill_rates_is_unknown(self):
        r = self.run_metric('unbilled_work')
        self.assertIsNone(r.value)
        self.assertFalse(r.is_complete)
        self.assertIn('2 entries', r.unknown_reason)
        self.assertEqual({x['client_id'] for x in self.rows('unbilled_work')}, {self.a.pk, self.b.pk})
        self.assertEqual([x['client_id'] for x in self.rows('unbilled_work', user=self.scoped)], [self.a.pk])

    def test_utilization_without_basis_is_unknown(self):
        r = self.run_metric('technician_utilization')
        self.assertEqual(r.state, 'ok')
        self.assertIsNone(r.value)
        self.assertFalse(r.is_complete)
        self.assertIn('2 technicians have no shifts', r.unknown_reason)
        self.assertEqual(len(self.rows('technician_utilization')), 2)

    def test_utilization_with_target(self):
        from resourcing.models import BillableTarget
        BillableTarget.objects.create(user=self.rated, target_hours_per_week=Decimal('40'), is_active=True)
        r = self.run_metric('technician_utilization', user=self.scoped)
        self.assertTrue(r.is_complete)
        self.assertIsNotNone(r.value)


# -- delivery ------------------------------------------------------------------

class DeliveryTests(Base):

    def test_unbilled_work_excludes_billed_and_nonbillable(self):
        from psa.models import Contract, Invoice, InvoiceLineItem, TicketTimeEntry
        Contract.objects.create(organization=self.a, client_org=self.a, name='hourly', status='active',
                                contract_type='block_hours', hourly_rate=Decimal('100'),
                                start_date=self.today - timedelta(days=30))
        t = self.ticket(self.a, 'work')
        start = self.now - timedelta(days=3)
        mk = lambda ticket, mins, **kw: TicketTimeEntry.objects.create(  # noqa: E731
            ticket=ticket, user=self.su, started_at=start, ended_at=start + timedelta(minutes=mins),
            duration_minutes=mins, **kw)
        mk(t, 90)
        billed = mk(t, 60)
        mk(t, 30, is_billable=False)
        inv = Invoice.objects.create(organization=self.a, client_org=self.a, title='x',
                                     invoice_date=self.today, status='draft')
        InvoiceLineItem.objects.create(invoice=inv, description='t', source='time', source_id=str(billed.pk))
        r = self.run_metric('unbilled_work')
        rows = self.rows('unbilled_work')
        self.assertEqual([(x['client_id'], x['entries']) for x in rows], [(self.a.pk, 1)])
        if r.is_complete:
            self.assertEqual(r.value, 150.0)  # 1.5 h at the contract's 100/h
        self.assertEqual(r.value, sum(x['amount'] for x in rows) if r.value is not None else None)

    def test_sla_attainment_matches_report_and_rows(self):
        from psa.models import Ticket
        ok = self.ticket(self.a, 'met', resolution_due_at=self.now + timedelta(days=1))
        late = self.ticket(self.a, 'late', status=self.status_closed,
                           resolution_due_at=self.now - timedelta(days=2), closed_at=self.now - timedelta(days=1))
        self.ticket(self.b, 'other', resolution_due_at=self.now + timedelta(days=1))
        r = self.run_metric('sla_attainment')
        self.assertAlmostEqual(r.value, 66.7)
        rows = self.rows('sla_attainment')
        self.assertEqual(len(rows), 3)
        self.assertEqual([x['id'] for x in rows if x['resolution_breached']], [late.pk])
        self.assertTrue(any(t['value'] is not None for t in r.trend))
        self.assertEqual(self.run_metric('sla_attainment', customer=self.a.pk).value, 50.0)
        self.assertIn(ok.pk, {x['id'] for x in rows})
        self.assertEqual(Ticket.objects.count(), 3)

    def test_backlog_and_location(self):
        t1 = self.ticket(self.a, 'open a', site=self.loc_a)
        t2 = self.ticket(self.b, 'open b')
        self.ticket(self.a, 'closed', status=self.status_closed)
        self.assertEqual(self.run_metric('ticket_backlog').value, 2)
        self.assertEqual({x['id'] for x in self.rows('ticket_backlog')}, {t1.pk, t2.pk})
        self.assertEqual([x['id'] for x in self.rows('ticket_backlog', location=self.loc_a.pk)], [t1.pk])

    def test_critical_issues_parts(self):
        from security_alerts.models import SecurityIncident
        p1 = self.ticket(self.a, 'down', priority=self.p1)
        self.ticket(self.a, 'p3 open')
        inc = SecurityIncident.objects.create(organization=self.b, client_org=self.b, title='ransomware',
                                              severity='critical')
        SecurityIncident.objects.create(organization=self.b, title='low one', severity='low')
        SecurityIncident.objects.create(organization=self.b, title='closed', severity='critical',
                                        status='closed')
        r = self.run_metric('critical_issues')
        self.assertEqual(r.value, 2)
        self.assertEqual([x['id'] for x in self.rows('critical_issues', part='p1')], [p1.pk])
        self.assertEqual([x['id'] for x in self.rows('critical_issues', part='incident')], [inc.pk])

    def test_critical_issues_without_security_permission_is_incomplete(self):
        from security_alerts.models import SecurityIncident
        self.ticket(self.a, 'down', priority=self.p1)
        SecurityIncident.objects.create(organization=self.a, title='x', severity='critical')
        r = self.run_metric('critical_issues', user=self.l1)
        self.assertEqual(r.value, 1)
        self.assertFalse(r.is_complete)
        self.assertIn('security_alerts_view', r.unknown_reason)


# -- risk / operations ---------------------------------------------------------

class RiskOpsTests(Base):

    def test_security_alerts_not_configured_then_counted(self):
        from security_alerts.models import SecurityAlert
        self.assertEqual(self.run_metric('security_issues').state, 'not_configured')
        a1 = SecurityAlert.objects.create(organization=self.a, external_id='1', title='EDR hit', severity='high')
        SecurityAlert.objects.create(organization=self.a, external_id='2', title='done', status='resolved')
        b1 = SecurityAlert.objects.create(organization=self.b, external_id='3', title='B', severity='low')
        r = self.run_metric('security_issues')
        self.assertEqual(r.value, 2)
        self.assertEqual({x['id'] for x in self.rows('security_issues')}, {a1.pk, b1.pk})
        self.assertEqual(r.secondary, '1 high or critical')

    def test_procurement(self):
        from psa.models import POBackOrder, PurchaseOrder, PurchaseOrderLineItem, PurchaseRequisition
        pr = PurchaseRequisition.objects.create(organization=self.a, pr_number='PR-1', title='laptops',
                                                status='submitted')
        PurchaseRequisition.objects.create(organization=self.a, pr_number='PR-2', title='x', status='draft')
        po = PurchaseOrder.objects.create(organization=self.b, client_org=self.b, po_number='PO-1',
                                          vendor_name='V', title='switches', status='sent')
        line = PurchaseOrderLineItem.objects.create(po=po, description='switch', quantity=2)
        bo = POBackOrder.objects.create(po=po, po_line=line, quantity_outstanding=Decimal('1'))
        r = self.run_metric('procurement_status')
        self.assertEqual(r.value, 3)
        self.assertEqual([x['id'] for x in self.rows('procurement_status', part='requisitions')], [pr.pk])
        self.assertEqual([x['id'] for x in self.rows('procurement_status', part='back_orders')], [bo.pk])
        self.assertEqual(self.run_metric('procurement_status', user=self.scoped).value, 1)

    def test_payments_not_configured_without_gateway(self):
        r = self.run_metric('payment_collection')
        self.assertEqual(r.state, 'not_configured')
        self.assertIsNone(r.value)

    def test_apps_not_installed_are_not_configured(self):
        from django.apps import apps
        for key, app in (('backup_failures', 'backup_monitoring'), ('licensing_renewals', 'licensing')):
            if apps.is_installed(app):
                continue
            r = self.run_metric(key)
            self.assertEqual(r.state, 'not_configured', key)
            self.assertIsNone(r.value, key)
            self.assertEqual(r.row_count, 0)

    def test_psa_off_is_not_configured(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        self.assertEqual(self.run_metric('revenue_trend').state, 'not_configured')

    def test_provider_error_is_contained(self):
        with mock.patch.object(providers.TicketBacklog, 'collect', side_effect=RuntimeError('boom')):
            r = self.run_metric('ticket_backlog')
        self.assertEqual(r.state, 'error')
        self.assertNotIn('boom', r.reason)


# -- tenancy, permissions, views -----------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AccessTests(Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from psa.models import Invoice
        d = cls.today - timedelta(days=2)
        cls.ia = Invoice.objects.create(organization=cls.a, client_org=cls.a, title='a', invoice_date=d,
                                        status='sent', total=Decimal('10'))
        cls.ib = Invoice.objects.create(organization=cls.b, client_org=cls.b, title='b', invoice_date=d,
                                        status='sent', total=Decimal('1000'))

    def get_json(self, user, name, key, **params):
        self.client.force_login(user)
        return self.client.get(reverse(name, args=[key]), params)

    def test_scoped_technician_sees_only_their_customer(self):
        r = self.run_metric('revenue_trend', user=self.scoped)
        self.assertEqual(r.value, Decimal('10.00'))
        self.assertEqual([x['id'] for x in self.rows('revenue_trend', user=self.scoped)], [self.ia.pk])
        r = self.run_metric('revenue_trend', user=self.scoped, customer=self.b.pk)
        self.assertEqual(r.state, 'forbidden')
        self.assertIsNone(r.value)

    def test_isolation_through_endpoints(self):
        data = self.get_json(self.scoped, 'executive:metric', 'revenue_trend').json()
        self.assertEqual(data['value'], 10.0)
        resp = self.get_json(self.scoped, 'executive:records', 'revenue_trend', customer=self.b.pk, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn('1000', resp.content.decode())
        rows = self.get_json(self.scoped, 'executive:records', 'revenue_trend', format='json').json()['rows']
        self.assertEqual([r['id'] for r in rows], [self.ia.pk])
        html = self.get_json(self.scoped, 'executive:records', 'revenue_trend').content.decode()
        self.assertIn(self.ia.invoice_number, html)
        self.assertNotIn(self.ib.invoice_number, html)
        # The customer picker offers only their customer.
        self.client.force_login(self.scoped)
        page = self.client.get(reverse('executive:overview')).content.decode()
        picker = page[page.index('id="bo-customer"'):]
        picker = picker[:picker.index('</select>')]
        self.assertIn('Alpha Exec', picker)
        self.assertNotIn('Bravo Exec', picker)

    def test_cache_is_per_scope(self):
        f = _filters()
        p = providers.get('revenue_trend')
        first = metrics.compute(p, self.su, f)
        self.assertFalse(first.cached)
        self.assertTrue(metrics.compute(p, self.su, f).cached)
        scoped = metrics.compute(p, self.scoped, f)
        self.assertFalse(scoped.cached)
        self.assertEqual(scoped.value, Decimal('10.00'))

    def test_superuser_page_lists_cards(self):
        self.client.force_login(self.su)
        resp = self.client.get(reverse('executive:overview'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for p in providers.PROVIDERS:
            self.assertIn(f'id="card-{p.key}"', html)

    def test_metric_json_shape(self):
        data = self.get_json(self.su, 'executive:metric', 'revenue_trend').json()
        for k in ('value', 'unit', 'trend', 'is_complete', 'unknown_reason', 'source', 'as_of',
                  'drilldown_url', 'supported_filters', 'state'):
            self.assertIn(k, data)
        self.assertTrue(data['drilldown_url'].startswith(reverse('executive:records', args=['revenue_trend'])))
        self.assertEqual(self.get_json(self.su, 'executive:metric', 'nope').status_code, 404)

    def test_role_without_financial_permission(self):
        self.assertEqual(self.get_json(self.l1, 'executive:metric', 'revenue_trend').status_code, 403)
        self.assertEqual(self.get_json(self.l1, 'executive:records', 'revenue_trend').status_code, 403)
        self.client.force_login(self.l1)
        html = self.client.get(reverse('executive:overview')).content.decode()
        self.assertNotIn('id="card-revenue_trend"', html)
        self.assertIn('id="card-critical_issues"', html)  # tickets_view is in the L1 role

    def test_customer_users_never_reach_the_page(self):
        self.client.force_login(self.customer)
        for url in (reverse('executive:overview'),
                    reverse('executive:metric', args=['revenue_trend']),
                    reverse('executive:records', args=['revenue_trend'])):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_anonymous_redirected(self):
        resp = self.client.get(reverse('executive:overview'))
        self.assertEqual(resp.status_code, 302)

    def test_page_has_no_audit_feed(self):
        self.client.force_login(self.su)
        html = self.client.get(reverse('executive:overview')).content.decode()
        start = html.index('id="bo"')
        self.assertNotIn('audit_log', html[start:])
        self.assertNotIn('Recent activity', html[start:])

    def test_navigation_entry(self):
        from core import navigation
        entry = [e for e in navigation.PRIMARY[0].entries if e.url_name == 'executive:overview']
        self.assertEqual(len(entry), 1)
        self.assertEqual(navigation.group_for('executive:overview'), 'dashboard')


class FilterTests(TestCase):

    def test_parse_and_clamp(self):
        f = Filters.from_query({'start': '2026-05-01', 'end': '2026-01-01', 'customer': 'x',
                                'service_line': 'bogus', 'location': '-3'})
        self.assertLess(f.start, f.end)
        self.assertIsNone(f.customer)
        self.assertEqual(f.service_line, '')
        self.assertIsNone(f.location)
        f = Filters.from_query({'start': '2010-01-01', 'end': '2026-01-01'})
        self.assertLessEqual((f.end - f.start).days, 366 * 3)

    def test_unsupported_filters_are_cleared(self):
        f = Filters.from_query({'customer': '4', 'service_line': 'retainer', 'location': '2'})
        g = f.for_provider((metrics.F_DATE, metrics.F_CUSTOMER))
        self.assertEqual((g.customer, g.service_line, g.location), (4, '', None))

    def test_every_provider_declares_filters_and_columns(self):
        for p in providers.PROVIDERS:
            self.assertTrue(p.key and p.title and p.source, p)
            self.assertTrue(p.columns, p.key)
            self.assertTrue(set(p.supported_filters) <= set(metrics.ALL_FILTERS), p.key)
        self.assertEqual(len({p.key for p in providers.PROVIDERS}), len(providers.PROVIDERS))
        json.dumps([p.meta() for p in providers.PROVIDERS])
