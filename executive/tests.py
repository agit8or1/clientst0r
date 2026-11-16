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
            billing_view_aging=True, tickets_view=True, procurement_view=True,
            security_alerts_view=True)
        cls.l1_role = RoleTemplate.objects.create(
            name='Exec L1', organization=None, reports_view_dashboards=True, tickets_view=True)
        cls.scoped = _make_msp_tech(User.objects.create_user('ex_scoped', 's@x.com', 'pw'), cls.owner_role)
        cls.scoped.profile.client_scope = 'selected'
        cls.scoped.profile.save()
        cls.scoped.profile.scope_organizations.set([cls.a])
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
        Invoice.objects.create(organization=cls.a, client_org=cls.a, title='draft', invoice_date=d,
                               status='draft', total=Decimal('999'))
        Invoice.objects.create(organization=cls.a, client_org=cls.a, title='void', invoice_date=d,
                               status='void', total=Decimal('999'))
        Invoice.objects.create(organization=cls.a, client_org=cls.a, title='old',
                               invoice_date=cls.today - timedelta(days=400), status='paid', total=Decimal('7'))
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

    def test_accounts_receivable(self):
        r = self.run_metric('accounts_receivable')
        # i1 100 outstanding (no due date: current), ib 50 at 45 days.
        self.assertEqual(r.value, Decimal('150.00'))
        buckets = {b['label']: b['value'] for b in r.breakdown}
        self.assertEqual(buckets['31–60 days'], Decimal('50.00'))
        self.assertEqual(buckets['Current'], Decimal('100.00'))
        self.assertEqual({x['id'] for x in self.rows('accounts_receivable')}, {self.i1.pk, self.ib.pk})
        self.assertIn('no accounting sync', r.source)

    def test_accounts_receivable_labels_synced_status(self):
        self.i1.provider_synced_at = timezone.now()
        self.i1.save(update_fields=['provider_synced_at'])
        r = self.run_metric('accounts_receivable')
        self.assertIn('synced from the accounting provider for 1 of 2', r.source)

    def test_service_line_is_ignored_by_ar(self):
        r = self.run_metric('accounts_receivable', service_line='retainer')
        self.assertIn('service_line', r.ignored_filters)
        self.assertEqual(r.value, Decimal('150.00'))

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
        self.assertEqual(self.run_metric('contract_renewals', service_line='managed_services').value, 1)

    def test_customer_growth(self):
        r = self.run_metric('customer_growth')
        self.assertEqual(r.value, 2)
        self.assertEqual({x['id'] for x in self.rows('customer_growth')}, {self.a.pk, self.b.pk})
        new = {b['label']: b['value'] for b in r.breakdown}['New customers in period']
        self.assertEqual(new, 0)  # Bravo's first contract started 300 days ago
        # Churn reporting is not on this branch: flagged, not zero.
        if providers._queries_fn('contract_churn') is None:
            self.assertFalse(r.is_complete)
            self.assertIn('contract churn', r.unknown_reason)

    def test_customer_growth_with_churn_function(self):
        churn = {'churned_count': 1, 'churned_mrr': 250.0, 'churn_rate_pct': 5.0, 'is_complete': True,
                 'undated_cancellations': 0}
        with mock.patch('reports.queries.contract_churn', create=True, return_value=churn) as fn:
            r = self.run_metric('customer_growth', customer=self.a.pk)
        self.assertEqual(fn.call_args[0][2], {self.a.pk})
        b = {x['label']: x['value'] for x in r.breakdown}
        self.assertEqual(b['Churned contracts'], 1)
        self.assertEqual(b['Revenue churn'], 5.0)
        self.assertTrue(r.is_complete)
        self.assertEqual(r.value, 1)


# -- delegated metrics (reports.queries functions from dev/profitability) ------

class DelegatedTests(Base):

    def test_mrr_not_configured_without_reporting_function(self):
        if providers._queries_fn('recurring_revenue') is not None:
            self.skipTest('recurring_revenue is installed')
        r = self.run_metric('mrr_arr')
        self.assertEqual(r.state, 'not_configured')
        self.assertIsNone(r.value)
        self.assertIn('dev/profitability', r.reason)

    def _rr(self, on_date, organization=None):
        return {'mrr': 1500.0, 'arr': 18000.0, 'contract_count': 1, 'contracts_without_amount': 2,
                'contracts_unknown_end': 1, 'is_complete': False,
                'contracts': [{'contract_id': 7, 'contract_name': 'Alpha MSA', 'client_id': self.a.pk,
                               'client_name': 'Alpha Exec', 'frequency': 'monthly', 'mrr': 1500.0,
                               'next_billing_date': None, 'end_date': None}]}

    def test_mrr_maps_reporting_function_and_propagates_incomplete(self):
        trend = {'points': [{'month': '2026-10', 'mrr': 1000.0, 'is_complete': True},
                            {'month': '2026-11', 'mrr': 1500.0, 'is_complete': True}], 'is_complete': True}
        with mock.patch('reports.queries.recurring_revenue', create=True, side_effect=self._rr) as rr, \
                mock.patch('reports.queries.mrr_trend', create=True, return_value=trend):
            r = self.run_metric('mrr_arr', user=self.scoped)
            rows = self.rows('mrr_arr', user=self.scoped)
        self.assertEqual(r.state, 'ok')
        self.assertEqual(r.value, 1500.0)
        self.assertEqual(r.breakdown[0], {'label': 'ARR', 'value': 18000.0, 'unit': 'currency'})
        self.assertFalse(r.is_complete)
        self.assertIn('1 stopped contracts have no end date', r.unknown_reason)
        self.assertEqual([p['value'] for p in r.trend], [1000.0, 1500.0])
        self.assertEqual([x['contract_id'] for x in rows], [7])
        # The scoped technician's customers are passed down.
        self.assertEqual(rr.call_args[0][1], {self.a.pk})

    def test_margin_not_configured_without_costing(self):
        if providers.has_costing():
            self.skipTest('reports.costing is installed')
        for key in ('gross_margin', 'customer_profitability'):
            r = self.run_metric(key)
            self.assertEqual(r.state, 'not_configured', key)
            self.assertIsNone(r.value)

    def _profit_rows(self, start, end, organization=None):
        return [
            {'client_id': self.a.pk, 'client_name': 'Alpha Exec', 'revenue': 1000.0, 'cost': 400.0,
             'margin': 600.0, 'margin_pct': 60.0, 'unknown_cost_hours': 0.0},
            {'client_id': self.b.pk, 'client_name': 'Bravo Exec', 'revenue': 500.0, 'cost': 300.0,
             'margin': None, 'margin_pct': None, 'unknown_cost_hours': 12.0},
        ]

    def _with_costing(self):
        return (mock.patch('executive.providers.has_costing', return_value=True),
                mock.patch('reports.queries.profitability_by_client', create=True,
                           side_effect=self._profit_rows))

    def test_gross_margin_incomplete_badge(self):
        p1, p2 = self._with_costing()
        with p1, p2:
            r = self.run_metric('gross_margin')
            rows = self.rows('gross_margin')
            scoped = self.run_metric('gross_margin', user=self.scoped)
        self.assertEqual(r.value, 46.7)  # (1500 - 700) / 1500
        self.assertFalse(r.is_complete)
        self.assertEqual(r.unknown_reason, '12 hours without a cost rate')
        self.assertEqual(r.label, 'Operational estimate, not accounting results')
        self.assertEqual({x['client_id'] for x in rows}, {self.a.pk, self.b.pk})
        # Scoped to Alpha: Bravo's revenue and unknown hours are not counted.
        self.assertEqual(scoped.value, 60.0)
        self.assertTrue(scoped.is_complete)

    def test_customer_profitability_ranks_and_flags_unranked(self):
        p1, p2 = self._with_costing()
        with p1, p2:
            r = self.run_metric('customer_profitability')
        self.assertEqual(r.value, 2)
        self.assertEqual([b['label'] for b in r.breakdown], ['Alpha Exec'])
        self.assertIn('1 customers cannot be ranked', r.unknown_reason)

    def test_cost_cards_feature_detect_view_profitability(self):
        p = providers.get('gross_margin')
        with mock.patch('executive.providers._perm_known', return_value=False):
            self.assertEqual(p.permission_key(), 'reports_view_financial')
            self.assertIn('reports_view_financial', p.permission_note)
        with mock.patch('executive.providers._perm_known', return_value=True):
            self.assertEqual(p.permission_key(), 'view_profitability')
            self.assertEqual(p.permission_note, '')

    def test_utilization(self):
        self.assertEqual(self.run_metric('technician_utilization').state,
                         'ok' if providers._queries_fn('utilization_summary') else 'not_configured')
        summary = {'rows': [{'tech_id': 1, 'tech_username': 'tech1', 'billable_hours': 30.0,
                             'available_hours': 40.0, 'basis': 'shifts', 'utilization_pct': 75.0},
                            {'tech_id': 2, 'tech_username': 'tech2', 'billable_hours': 5.0,
                             'available_hours': None, 'basis': None, 'utilization_pct': None}],
                   'utilization_pct': 75.0, 'billable_hours': 30.0, 'available_hours': 40.0,
                   'techs_without_basis': 1, 'is_complete': False}
        with mock.patch('reports.queries.utilization_summary', create=True, return_value=summary):
            r = self.run_metric('technician_utilization')
            rows = self.rows('technician_utilization')
        self.assertEqual(r.value, 75.0)
        self.assertFalse(r.is_complete)
        self.assertIn('1 technicians have no shifts', r.unknown_reason)
        self.assertEqual(len(rows), 2)


# -- delivery ------------------------------------------------------------------

class DeliveryTests(Base):

    def test_unbilled_work_excludes_billed_and_nonbillable(self):
        from psa.models import Invoice, InvoiceLineItem, TicketTimeEntry
        t = self.ticket(self.a, 'work', site=self.loc_a)
        tb = self.ticket(self.b, 'work b')
        start = self.now - timedelta(days=3)
        mk = lambda ticket, mins, **kw: TicketTimeEntry.objects.create(  # noqa: E731
            ticket=ticket, user=self.su, started_at=start, ended_at=start + timedelta(minutes=mins),
            duration_minutes=mins, **kw)
        e1 = mk(t, 90)
        billed = mk(t, 60)
        mk(t, 30, is_billable=False)
        e4 = mk(tb, 30)
        inv = Invoice.objects.create(organization=self.a, client_org=self.a, title='x',
                                     invoice_date=self.today, status='draft')
        InvoiceLineItem.objects.create(invoice=inv, description='t', source='time', source_id=str(billed.pk))
        r = self.run_metric('unbilled_work')
        self.assertEqual({x['id'] for x in self.rows('unbilled_work')}, {e1.pk, e4.pk})
        if not providers.has_costing():
            self.assertEqual(r.value, 2.0)
            self.assertEqual(r.unit, 'hours')
        self.assertEqual({x['id'] for x in self.rows('unbilled_work', location=self.loc_a.pk)}, {e1.pk})

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
        self.assertIn('Alpha Exec', page)
        self.assertNotIn('Bravo Exec', page)

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
