"""v3.17.681 dashboard work: sales widgets (quotes, PSA contracts, contract
documents, won / lost, sales activity), manager widgets (utilization,
billing, reports), role configuration (available widgets, actions, landing
page, sidebar mode, role mapping), customer-dashboard isolation, the
checked "View all" links, workflow E links and query budgets."""
import json
import time
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile
from core import dashboard_widgets as dw
from core.models import DashboardRoleDefault, DashboardRoleMapping, Organization, SystemSetting
from core.tests.test_dashboard_roles import _role
from core.tests.test_dashboard_widgets import _req
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed

User = get_user_model()

SALES_KEYS = {'kpi_quotes_open', 'kpi_quotes_waiting', 'kpi_contracts_signing',
              'kpi_contracts_expiring', 'kpi_crm_won', 'quotes', 'contract_docs',
              'contract_renewals', 'crm_won_lost', 'crm_activity'}
MANAGER_KEYS = {'team_utilization', 'billing_summary', 'reports'}


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        s = SystemSetting.get_settings()
        s.crm_enabled = True
        s.save()
        cls.org_a = Organization.objects.create(name='Sales Alpha', slug='sales-alpha')
        cls.org_b = Organization.objects.create(name='Sales Bravo Secret', slug='sales-bravo')
        cls.root = User.objects.create_superuser('r681_root', 'r@x.com', 'pw')
        cls.users = {}
        for seed in ('service_manager', 'tech_l1', 'tech_l2', 'sales_rep', 'billing_finance',
                     'auditor', 'org_owner'):
            u = _make_msp_tech(User.objects.create_user(f'r681_{seed}', f'{seed}@x.com', 'pw'))
            u.profile.global_role_template = _role(seed)
            u.profile.save()
            Membership.objects.create(user=u, organization=cls.org_a, role=Role.EDITOR,
                                      role_template=_role(seed))
            cls.users[seed] = u
        cls.customer = User.objects.create_user('r681_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=cls.customer, organization=cls.org_a, role=Role.EDITOR,
                                  role_template=_role('customer_user'))
        cls.cust_admin = User.objects.create_user('r681_cust_admin', 'ca@x.com', 'pw')
        Membership.objects.create(user=cls.cust_admin, organization=cls.org_a, role=Role.ADMIN,
                                  role_template=_role('customer_admin'))

    def user(self, seed):
        return User.objects.get(pk=self.users[seed].pk)

    def _login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        # force_login sends user_logged_in, which arms the one-time landing
        # redirect; tests that want it use _signed_in.
        s.pop('dash_landing_at', None)
        s['2fa_prompted'] = True
        s['current_organization_id'] = (org or self.org_a).pk
        s.save()

    def allowed(self, user, org=None):
        req = _req(user, org or self.org_a)
        return {w.key for w in dw.WIDGETS if dw.widget_available(req, w)}


def _ticket(org, subject, **kw):
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    base = dict(queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                ticket_type=TicketType.objects.first(),
                status=TicketStatus.objects.filter(is_terminal=False, pauses_sla=False).first())
    base.update(kw)
    return Ticket.objects.create(organization=org, subject=subject, **base)


def _quote(org, client, status, total, **kw):
    from psa.models import Quote
    q = Quote.objects.create(organization=org, client_org=client, title=kw.pop('title', 'Q'),
                             status=status, **kw)
    Quote.objects.filter(pk=q.pk).update(total=Decimal(total))
    return q


class SalesWidgetTests(_Base):

    def test_sales_rep_gets_sales_widgets_customers_never(self):
        allowed = self.allowed(self.user('sales_rep'))
        for key in ('kpi_quotes_open', 'quotes', 'contract_docs', 'kpi_contracts_signing',
                    'contract_renewals', 'crm_won_lost', 'crm_activity'):
            self.assertIn(key, allowed)
        for user in (self.customer, self.cust_admin):
            with self.subTest(user=user.username):
                self.assertFalse(self.allowed(user) & (SALES_KEYS | MANAGER_KEYS))

    def test_sales_preset_shows_them(self):
        req = _req(self.user('sales_rep'), self.org_a)
        shown = {p.key for p in dw.visible_widgets(req) if not p.hidden}
        for key in ('crm_pipeline', 'quotes', 'contract_docs', 'kpi_quotes_open',
                    'kpi_contracts_signing'):
            self.assertIn(key, shown)

    def test_quotes_need_psa_and_quotes_view(self):
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        self.assertNotIn('quotes', self.allowed(self.user('sales_rep')))

    def test_quote_figures_are_the_selected_customers(self):
        from psa.models import PSAApproval
        _quote(self.org_a, self.org_a, 'draft', '100')
        sent = _quote(self.org_a, self.org_a, 'sent', '250', title='Firewall refresh',
                      sent_at=timezone.now() - timedelta(days=2))
        _quote(self.org_a, self.org_a, 'accepted', '400', accepted_at=timezone.now())
        _quote(self.org_a, self.org_a, 'accepted', '999', accepted_at=timezone.now() - timedelta(days=60))
        _quote(self.org_b, self.org_b, 'sent', '7777', title='Bravo secret quote')
        PSAApproval.objects.create(organization=self.org_a, kind='quote', object_type='psa.Quote',
                                   object_id=sent.pk, status='pending')
        req = _req(self.user('sales_rep'), self.org_a)
        ctx = dw.build_quotes(req, self.org_a)
        by = {r['label']: r for r in ctx['rows']}
        self.assertEqual(by['Draft']['count'], 1)
        self.assertEqual(by['Sent, awaiting the customer']['count'], 1)
        self.assertEqual(by['Sent, awaiting the customer']['value'], Decimal('250'))
        self.assertEqual(by['Awaiting internal approval']['count'], 1)
        self.assertEqual(by['Accepted (last 30 days)']['count'], 1)
        self.assertEqual(ctx['open_value'], Decimal('350'))
        self.assertEqual([q['title'] for q in ctx['waiting']], ['Firewall refresh'])
        kpi = dw.build_kpi_quotes_waiting(req, self.org_a)
        self.assertEqual(kpi['value'], 1)
        self.assertIn('1 awaiting approval', kpi['sub'])

    def test_contract_renewals(self):
        from psa.models import Contract
        today = timezone.localdate()
        Contract.objects.create(organization=self.org_a, client_org=self.org_a, name='Renews',
                                status='active', start_date=today - timedelta(days=300),
                                end_date=today + timedelta(days=20), auto_renew=True)
        Contract.objects.create(organization=self.org_a, client_org=self.org_a, name='Ends',
                                status='active', start_date=today - timedelta(days=300),
                                end_date=today + timedelta(days=30))
        Contract.objects.create(organization=self.org_a, client_org=self.org_a, name='Later',
                                status='active', start_date=today, end_date=today + timedelta(days=300))
        Contract.objects.create(organization=self.org_b, client_org=self.org_b, name='Bravo',
                                status='active', start_date=today, end_date=today + timedelta(days=5))
        ctx = dw.build_contract_renewals(_req(self.user('sales_rep'), self.org_a), self.org_a)
        self.assertEqual(ctx['agg'], {'active': 3, 'renewing': 1, 'expiring': 1, 'lapsed': 0})
        self.assertEqual([r['name'] for r in ctx['rows']], ['Renews', 'Ends'])

    def test_contract_documents_scoped_and_pricing(self):
        from contracts.models import ContractDocument as D
        now = timezone.now()
        D.objects.create(organization=self.org_a, reference='C-1', title='MSA Alpha', status=D.SENT,
                         sent_at=now - timedelta(days=5))
        D.objects.create(organization=self.org_a, reference='C-2', title='Signed', status=D.SIGNED,
                         signed_at=now - timedelta(days=2), recurring_total=Decimal('120'))
        D.objects.create(organization=self.org_b, reference='C-3', title='Bravo doc', status=D.SENT,
                         sent_at=now)
        rep = _req(self.user('sales_rep'), self.org_a)
        ctx = dw.build_contract_docs(rep, self.org_a)
        by = {r['label']: r['count'] for r in ctx['rows']}
        self.assertEqual(by['Awaiting signature'], 1)
        self.assertEqual(by['Signed (last 30 days)'], 1)
        self.assertEqual([f['title'] for f in ctx['follow']], ['MSA Alpha'])
        self.assertTrue(ctx['pricing'])
        self.assertEqual(ctx['signed_recurring'], Decimal('120'))
        # The auditor reads contracts but not their pricing: no totals.
        aud = _req(self.user('auditor'), self.org_a)
        if dw.gate_contract_docs(aud):
            ctx = dw.build_contract_docs(aud, self.org_a)
            self.assertFalse(ctx['pricing'])
            self.assertIsNone(ctx['signed_recurring'])

    def test_won_lost_and_activity(self):
        from crm.models import Opportunity, SalesActivity
        today = timezone.localdate()
        Opportunity.objects.create(organization=self.org_a, client_org=self.org_a, name='Won one',
                                   stage='closed_won', estimated_value=1000, actual_close_date=today)
        Opportunity.objects.create(organization=self.org_a, client_org=self.org_a, name='Lost one',
                                   stage='closed_lost', estimated_value=500, actual_close_date=today)
        Opportunity.objects.create(organization=self.org_b, client_org=self.org_b, name='Bravo won',
                                   stage='closed_won', estimated_value=9, actual_close_date=today)
        opp = Opportunity.objects.create(organization=self.org_a, client_org=self.org_a, name='Open')
        SalesActivity.objects.create(organization=self.org_a, opportunity=opp, subject='Called CFO')
        SalesActivity.objects.create(organization=self.org_b, client_org=self.org_b,
                                     subject='Bravo secret call')
        req = _req(self.user('sales_rep'), self.org_a)
        f = dw.build_crm_won_lost(req, self.org_a)['f']
        self.assertEqual((f['won'], f['lost'], f['rate']), (1, 1, 50))
        rows = dw.build_crm_activity(req, self.org_a)['rows']
        self.assertEqual([r['subject'] for r in rows], ['Called CFO'])
        self.assertTrue(rows[0]['url'].endswith(f'/opportunities/{opp.pk}/'))

    def test_pipeline_link_falls_back_without_manage_pipeline(self):
        # The auditor holds crm_view but not crm_manage_pipeline: the board
        # would 403, so figures and "View all" point at the opportunity list.
        aud = _req(self.user('auditor'), self.org_a)
        self.assertEqual(dw.pipeline_url(aud), reverse('crm:opportunity_list'))
        self.assertEqual(dw.pipeline_url(_req(self.user('sales_rep'), self.org_a)),
                         reverse('crm:pipeline'))


class ManagerWidgetTests(_Base):

    def test_escalated_kpi_counts_open_escalated_tickets_of_this_customer(self):
        now = timezone.now()
        _ticket(self.org_a, 'Esc A', escalated_at=now)
        _ticket(self.org_a, 'Not escalated')
        _ticket(self.org_b, 'Esc B secret', escalated_at=now)
        req = _req(self.user('service_manager'), self.org_a)
        k = dw.build_kpi_escalated(req, self.org_a)
        self.assertEqual(k['value'], 1)
        self.assertTrue(k['href'].endswith(f'?client={self.org_a.pk}&view=escalated'))
        for preset in (dw.PRESET_L2, dw.PRESET_L3, dw.PRESET_MANAGER):
            self.assertNotIn('kpi_escalated', dw.preset_layout(preset)['hidden'], preset)
        self.assertIn('kpi_escalated', dw.MSP_ONLY)

    def test_utilization_not_configured_without_targets(self):
        req = _req(self.user('service_manager'), self.org_a)
        self.assertTrue(dw.gate_utilization(req))
        ctx = dw.build_team_utilization(req, self.org_a)
        self.assertEqual(ctx['rows'], [])
        self.assertIsNone(ctx['team_pct'])
        self.assertGreater(ctx['no_target'], 0)

    def test_utilization_against_targets(self):
        from psa.models import Ticket, TicketTimeEntry
        from resourcing.models import BillableTarget
        tech = self.user('tech_l1')
        BillableTarget.objects.create(user=tech, target_hours_per_week=10)
        t = _ticket(self.org_a, 'Work')
        start = timezone.now() - timedelta(minutes=5)
        TicketTimeEntry.objects.create(ticket=t, user=tech, started_at=start,
                                       ended_at=start + timedelta(hours=5), duration_minutes=300,
                                       is_billable=True)
        ctx = dw.build_team_utilization(_req(self.user('service_manager'), self.org_a), self.org_a)
        row = next(r for r in ctx['rows'] if r['name'] == tech.get_username())
        self.assertEqual(row['pct'], 50)
        self.assertEqual(ctx['team_pct'], 50)

    def test_utilization_gate(self):
        self.assertFalse(dw.gate_utilization(_req(self.user('tech_l1'), self.org_a)))
        self.assertFalse(dw.gate_utilization(_req(self.cust_admin, self.org_a)))

    def test_billing_needs_invoice_permission(self):
        self.assertTrue(dw.gate_billing(_req(self.user('billing_finance'), self.org_a)))
        self.assertFalse(dw.gate_billing(_req(self.user('tech_l2'), self.org_a)))
        self.assertFalse(dw.gate_billing(_req(self.cust_admin, self.org_a)))

    def test_billing_summary_figures(self):
        from psa.models import Invoice
        today = timezone.localdate()
        Invoice.objects.create(organization=self.org_a, client_org=self.org_a, title='A',
                               status='sent', invoice_date=today, due_date=today - timedelta(days=3),
                               total=Decimal('100'), amount_paid=Decimal('40'))
        Invoice.objects.create(organization=self.org_a, client_org=self.org_a, title='B',
                               status='draft', invoice_date=today, total=Decimal('50'))
        Invoice.objects.create(organization=self.org_b, client_org=self.org_b, title='C',
                               status='sent', invoice_date=today, total=Decimal('9999'))
        agg = dw.build_billing_summary(_req(self.user('billing_finance'), self.org_a), self.org_a)['agg']
        self.assertEqual(agg['open'], 1)
        self.assertEqual(agg['open_balance'], Decimal('60'))
        self.assertEqual(agg['overdue'], 1)
        self.assertEqual(agg['draft'], 1)

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_reports_links_follow_the_sidebar(self):
        self._login(self.user('service_manager'))
        r = self.client.get(reverse('core:dashboard_widget', args=['reports']))
        self.assertEqual(r.status_code, 200)
        # Every link it draws opens for this user.
        import re
        for href in re.findall(r'href="([^"]+)"', r.content.decode()):
            with self.subTest(href=href):
                self.assertNotIn(self.client.get(href).status_code, (403, 404))

    def test_manager_preset(self):
        shown = {p.key for p in dw.visible_widgets(_req(self.user('service_manager'), self.org_a))
                 if not p.hidden}
        self.assertTrue({'unassigned_queue', 'workload', 'sla_overview', 'team_utilization'} <= shown)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleConfigTests(_Base):

    def _cfg(self, preset, **kw):
        row, _ = DashboardRoleDefault.objects.get_or_create(preset=preset)
        for k, v in kw.items():
            setattr(row, k, v)
        row.save()
        return row

    def test_disabled_widget_cannot_be_shown_or_fetched(self):
        self._cfg(dw.PRESET_L1, disabled_widgets=['my_queue', 'sla_overview'])
        tech = self.user('tech_l1')
        # Even a personal layout that lists it does not bring it back.
        UserProfile.objects.filter(user=tech).update(dashboard_layout={
            'order': ['my_queue', 'sla_overview', 'tasks'], 'hidden': [], 'sizes': {}})
        self._login(tech)
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        keys = {p.key for p in r.context['grid']}
        listed = {p.key for p in r.context['customize']['grid']}
        self.assertNotIn('my_queue', keys)
        self.assertNotIn('my_queue', listed)  # not addable from Customize
        self.assertIn('tasks', keys)
        self.assertEqual(self.client.get(reverse('core:dashboard_widget', args=['sla_overview'])).status_code,
                         404)
        # Other roles keep it.
        self.assertIn('my_queue', self.allowed(self.user('tech_l2')))

    def test_enabling_never_grants(self):
        # A role configuration that lists every widget as available does not
        # get a customer anything their gates refuse.
        self._cfg(dw.PRESET_CUSTOMER, disabled_widgets=[], layout={'order': list(dw.KEYS), 'hidden': [],
                                                                   'sizes': {}})
        allowed = self.allowed(self.customer)
        self.assertFalse(allowed & (dw.MSP_ONLY - {'kpi_psa_companies', 'kpi_psa_tickets'}))

    def test_2fa_banner_cannot_be_disabled(self):
        self.assertEqual(dw.clean_disabled_widgets(['security_2fa', 'nope', 'tasks', 'tasks']), ['tasks'])

    def test_disabled_actions(self):
        req = _req(self.user('service_manager'), self.org_a)
        self.assertIn('dispatch_board', {a['key'] for a in dw.header_actions(req)})
        self._cfg(dw.PRESET_MANAGER, disabled_actions=['header:dispatch_board', 'qa:new_ticket'])
        req = _req(self.user('service_manager'), self.org_a)
        self.assertNotIn('dispatch_board', {a['key'] for a in dw.header_actions(req)})
        self.assertNotIn('new_ticket', {a['key'] for a in dw.build_quick_actions(req, self.org_a)['actions']})
        self.assertEqual(dw.clean_disabled_actions(['header:dispatch_board', 'bogus', 'qa:new_ticket']),
                         ['header:dispatch_board', 'qa:new_ticket'])

    def test_actions_config_never_adds(self):
        # A customer user cannot add a client; an empty disabled list changes nothing.
        self._cfg(dw.PRESET_CUSTOMER, disabled_actions=[])
        self.assertNotIn('add_client', {a['key'] for a in dw.header_actions(_req(self.customer, self.org_a))})

    def test_role_mapping_for_a_new_role(self):
        dispatcher = RoleTemplate.objects.create(name='Dispatcher', audience='internal')
        u = _make_msp_tech(User.objects.create_user('r681_disp', 'd@x.com', 'pw'))
        u.profile.global_role_template = dispatcher
        u.profile.save()
        self.assertEqual(dw.preset_for_user(User.objects.get(pk=u.pk)), dw.PRESET_L2)
        DashboardRoleMapping.objects.create(role_template=dispatcher, preset=dw.PRESET_MANAGER)
        self.assertEqual(dw.preset_for_user(User.objects.get(pk=u.pk)), dw.PRESET_MANAGER)
        # Service managers keep the dispatcher layout by default.
        self.assertEqual(dw.preset_for_user(self.user('service_manager')), dw.PRESET_MANAGER)

    def test_mapping_never_applies_to_customers(self):
        DashboardRoleMapping.objects.create(role_template=_role('customer_admin'), preset=dw.PRESET_ADMIN)
        self.assertEqual(dw.preset_for_user(self.cust_admin), dw.PRESET_CUSTOMER)

    def test_settings_page_permission(self):
        url = reverse('core:dashboard_role_settings')
        for user in (self.user('tech_l2'), self.customer, self.cust_admin):
            self._login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {'form': 'preset', 'preset': 'tech_l1'}).status_code,
                                 403)
        self.assertFalse(DashboardRoleDefault.objects.exists())
        self._login(self.root)
        r = self.client.get(url + '?preset=sales')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Role Dashboards')

    def test_settings_page_save(self):
        self._login(self.root)
        url = reverse('core:dashboard_role_settings')
        keep = [w.key for w in dw.WIDGETS if w.hideable and w.key != 'my_time']
        actions = [k for k, _l in dw.action_keys() if k != 'header:log_time']
        r = self.client.post(url, {'form': 'preset', 'preset': 'tech_l1', 'widget': keep,
                                   'action': actions, 'landing': reverse('psa:my_work'),
                                   'sidebar_mode': 'rail'})
        self.assertEqual(r.status_code, 302)
        row = DashboardRoleDefault.objects.get(preset='tech_l1')
        self.assertEqual(row.disabled_widgets, ['my_time'])
        self.assertEqual(row.disabled_actions, ['header:log_time'])
        self.assertEqual(row.landing, reverse('psa:my_work'))
        self.assertEqual(row.sidebar_mode, 'rail')

    def test_settings_page_rejects_foreign_landing(self):
        self._login(self.root)
        url = reverse('core:dashboard_role_settings')
        for bad in ('https://evil.example/', '//evil.example/', '/no/such/page/',
                    reverse('core:dashboard')):
            self.client.post(url, {'form': 'preset', 'preset': 'tech_l1', 'landing': bad})
            self.assertEqual(DashboardRoleDefault.objects.filter(preset='tech_l1').exclude(
                landing='').count(), 0, bad)

    def test_mapping_form(self):
        dispatcher = RoleTemplate.objects.create(name='Dispatcher', audience='internal')
        self._login(self.root)
        url = reverse('core:dashboard_role_settings')
        self.client.post(url, {'form': 'mappings', f'role_{dispatcher.pk}': 'manager'})
        self.assertEqual(DashboardRoleMapping.objects.get(role_template=dispatcher).preset, 'manager')
        self.client.post(url, {'form': 'mappings', f'role_{dispatcher.pk}': 'customer'})
        self.assertFalse(DashboardRoleMapping.objects.filter(role_template=dispatcher).exists())

    def _signed_in(self, user):
        self._login(user)
        s = self.client.session
        s['dash_landing_at'] = int(time.time())
        s.save()

    def test_landing_after_sign_in(self):
        self._cfg(dw.PRESET_L1, landing=reverse('psa:my_work'))
        self._signed_in(self.user('tech_l1'))
        r = self.client.get(reverse('core:dashboard'))
        self.assertRedirects(r, reverse('psa:my_work'), fetch_redirect_response=False)
        # Once only: the next visit is the dashboard.
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)

    def test_landing_ignored_when_the_user_may_not_open_it(self):
        # A landing page the role's user cannot open (Role Dashboards for a
        # technician without role-default management) leaves them on the
        # dashboard.
        self._cfg(dw.PRESET_L1, landing=reverse('core:dashboard_role_settings'))
        self._signed_in(self.user('tech_l1'))
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)
        # A customer with a staff-only landing page saved for their preset.
        self._cfg(dw.PRESET_CUSTOMER, landing=reverse('crm:home'))
        self._signed_in(self.customer)
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)

    def test_landing_stale_or_not_after_sign_in(self):
        self._cfg(dw.PRESET_L1, landing=reverse('psa:my_work'))
        self._login(self.user('tech_l1'))
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)
        s = self.client.session
        s['dash_landing_at'] = int(time.time()) - 3600
        s.save()
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)

    def test_sign_in_signal_respects_next(self):
        from types import SimpleNamespace
        from core.dashboard_views import note_sign_in
        sess = {}
        note_sign_in(None, SimpleNamespace(session=sess, POST={}, GET={'next': '/psa/'}), None)
        self.assertNotIn('dash_landing_at', sess)
        note_sign_in(None, SimpleNamespace(session=sess, POST={}, GET={}), None)
        self.assertIn('dash_landing_at', sess)

    def test_role_ui_defaults_context(self):
        self._cfg(dw.PRESET_L1, sidebar_mode='rail', landing=reverse('psa:my_work'))
        self._login(self.user('tech_l1'))
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.context['role_ui_defaults']['sidebar_mode'], 'rail')
        self._login(self.user('tech_l2'))
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.context['role_ui_defaults']['sidebar_mode'], '')

    def test_settings_entry_in_settings_center(self):
        from core import navigation as nav
        self.assertEqual(nav.section_for('core:dashboard_role_settings').key, 'settings_access')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerDashboardIsolationTests(_Base):
    """Every card, panel and action a customer user gets carries their own
    customer's data only."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from assets.models import Asset
        from crm.models import Opportunity
        from psa.models import Ticket
        for org, tag in ((cls.org_a, 'Alpha'), (cls.org_b, 'BravoLeak')):
            _ticket(org, f'{tag} shared ticket', client_can_view=True)
            _ticket(org, f'{tag} internal ticket', client_can_view=False)
            Asset.objects.create(organization=org, name=f'{tag} server')
            Opportunity.objects.create(organization=org, client_org=org, name=f'{tag} deal')
            _quote(org, org, 'sent', '10', title=f'{tag} quote')

    def test_every_customer_widget(self):
        for user in (self.customer, self.cust_admin):
            self._login(user)
            r = self.client.get(reverse('core:dashboard'))
            self.assertEqual(r.status_code, 200)
            html = r.content.decode()
            with self.subTest(user=user.username, part='page'):
                self.assertNotIn('BravoLeak', html)
                self.assertNotIn('Sales Bravo Secret', html)
                self.assertNotIn('internal ticket', html)
            req = _req(user, self.org_a)
            for w in dw.WIDGETS:
                if w.zone not in ('grid', 'kpi'):
                    continue
                resp = self.client.get(reverse('core:dashboard_widget', args=[w.key]))
                with self.subTest(user=user.username, widget=w.key):
                    if w.key in dw.MSP_ONLY:
                        self.assertEqual(resp.status_code, 404)
                    if resp.status_code == 200:
                        body = resp.content.decode()
                        self.assertNotIn('BravoLeak', body)
                        self.assertNotIn('Sales Bravo Secret', body)
                        self.assertNotIn('internal ticket', body)
                        self.assertNotIn('Alpha deal', body)
                        self.assertNotIn('Alpha quote', body)
                    self.assertEqual(resp.status_code == 200 or resp.status_code == 404, True)
            # Header actions: none that opens MSP-only pages.
            keys = {a['key'] for a in dw.header_actions(req)}
            self.assertFalse(keys & {'add_client', 'dispatch_board', 'log_time'})

    def test_customer_cannot_select_another_customer(self):
        self._login(self.customer, self.org_b)
        r = self.client.get(reverse('core:dashboard_widget', args=['kpi_tickets']))
        if r.status_code == 200:
            self.assertNotIn('BravoLeak', r.content.decode())
        r = self.client.get(reverse('core:dashboard'))
        self.assertNotIn('BravoLeak', r.content.decode())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CheckedLinkTests(_Base):

    def test_view_all_links_open(self):
        import re
        for seed in ('auditor', 'sales_rep', 'service_manager', 'tech_l1'):
            user = self.user(seed)
            UserProfile.objects.filter(user=user).update(dashboard_layout={
                'order': list(dw.KEYS), 'hidden': [], 'sizes': {}})
            self._login(user)
            r = self.client.get(reverse('core:dashboard'))
            for p in r.context['grid']:
                if not p.link:
                    continue
                with self.subTest(seed=seed, widget=p.key):
                    self.assertNotIn(self.client.get(p.link).status_code, (403, 404), p.link)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkflowLinkTests(_Base):

    def test_opportunity_quote_client_links(self):
        from crm.models import Opportunity
        q = _quote(self.org_a, self.org_a, 'draft', '10', title='Linked quote')
        opp = Opportunity.objects.create(organization=self.org_a, client_org=self.org_a, name='Deal',
                                         quote=q)
        self._login(self.user('sales_rep'))
        r = self.client.get(reverse('crm:opportunity_detail', args=[opp.pk]))
        self.assertContains(r, reverse('psa:quote_detail', args=[q.pk]))
        self.assertContains(r, reverse('accounts:organization_detail', args=[self.org_a.pk]))
        r = self.client.get(reverse('psa:quote_detail', args=[q.pk]))
        self.assertContains(r, reverse('crm:opportunity_detail', args=[opp.pk]))

    def test_quote_page_hides_opportunity_without_crm_view(self):
        from crm.models import Opportunity
        q = _quote(self.org_a, self.org_a, 'draft', '10')
        opp = Opportunity.objects.create(organization=self.org_a, client_org=self.org_a, name='Deal',
                                         quote=q)
        self._login(self.user('tech_l2'))
        r = self.client.get(reverse('psa:quote_detail', args=[q.pk]))
        if r.status_code == 200:
            self.assertNotContains(r, reverse('crm:opportunity_detail', args=[opp.pk]))

    def test_contract_document_and_billing_contract(self):
        from contracts.models import ContractDocument as D
        from psa.models import Contract
        today = timezone.localdate()
        pc = Contract.objects.create(organization=self.org_a, client_org=self.org_a, name='Billing',
                                     status='active', start_date=today)
        doc = D.objects.create(organization=self.org_a, reference='C-9', title='MSA', billing_contract=pc)
        self._login(self.user('sales_rep'))
        r = self.client.get(reverse('psa:contract_detail', args=[pc.pk]))
        self.assertContains(r, reverse('contracts:detail', args=[doc.pk]))
        r = self.client.get(reverse('contracts:detail', args=[doc.pk]))
        self.assertContains(r, reverse('psa:contract_detail', args=[pc.pk]))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QueryBudgetTests(_Base):
    """Query counts for the dashboard page and its widget endpoint (bounds
    a little above the measured numbers, so an N+1 shows up)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from psa.models import Ticket
        tech = cls.users['tech_l1']
        for i in range(40):
            _ticket(cls.org_a, f'Load {i}', assigned_to=tech if i % 2 else None)

    def _count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return len(ctx.captured_queries)

    def test_dashboard_page_budget(self):
        budgets = {'tech_l1': 90, 'service_manager': 90, 'sales_rep': 90}
        for seed, budget in budgets.items():
            self._login(self.user(seed))
            self.client.get(reverse('core:dashboard'))  # warm per-process caches
            n = self._count(reverse('core:dashboard'))
            with self.subTest(seed=seed):
                self.assertLessEqual(n, budget)
        self._login(self.customer)
        self.client.get(reverse('core:dashboard'))
        self.assertLessEqual(self._count(reverse('core:dashboard')), 90)

    def test_queue_widget_has_no_n_plus_one(self):
        self._login(self.user('tech_l1'))
        self.client.get(reverse('core:dashboard_widget', args=['my_queue']))  # warm per-process caches
        n = self._count(reverse('core:dashboard_widget', args=['my_queue']))
        from psa.models import Ticket
        tech = self.users['tech_l1']
        for i in range(20):
            _ticket(self.org_a, f'More {i}', assigned_to=tech)
        self.assertEqual(self._count(reverse('core:dashboard_widget', args=['my_queue'])), n)

    def test_sales_widgets_budget(self):
        self._login(self.user('sales_rep'))
        for key in ('quotes', 'contract_docs', 'contract_renewals', 'crm_won_lost', 'crm_activity'):
            with self.subTest(key=key):
                self.assertLessEqual(self._count(reverse('core:dashboard_widget', args=[key])), 40)
