"""
Roles & permissions program (authz-ops): server-side checks on report pages,
exports, generated reports, scheduled reports, saved queries and widgets.

The technician role used throughout mirrors the built-in RMM L1 template:
dashboards yes, financial / billing / audit no. Before this change such a
technician could open AR aging, MRR, hardware margin and agreement
reconciliation (staff-only, no role flag), and a technician whose global role
lacked reports_view_financial could still read every customer's
profitability through a single customer membership that granted it.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile, UserType
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed


def _staff(username, global_role=None):
    user = User.objects.create_user(username, f'{username}@msp.test', 'pw-authz-123')
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = global_role
    profile.save()
    return user


def _role(name, **flags):
    return RoleTemplate.objects.create(name=name, **flags)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReportPageFlagTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.acme = Organization.objects.create(name='Acme', slug='authz-rep-acme')
        cls.l1_role = _role('AuthzL1', reports_view_dashboards=True, tickets_view=True,
                            reports_view_financial=False, billing_view_aging=False,
                            billing_view_invoices=False, audit_view=False)
        cls.fin_role = _role('AuthzFinance', reports_view_dashboards=True,
                             reports_view_financial=True, billing_view_aging=True,
                             billing_view_invoices=True)
        cls.l1 = _staff('authz_l1', cls.l1_role)
        cls.finance = _staff('authz_fin', cls.fin_role)
        cls.legacy = _staff('authz_legacy')  # MSP staff, no global role
        cls.su = User.objects.create_superuser('authz_su', 'su@msp.test', 'pw-authz-123')
        # The L1 tech is also Owner of one customer: that membership must
        # not unlock every customer's figures.
        Membership.objects.create(user=cls.l1, organization=cls.acme, role=Role.OWNER)

    def _get(self, user, name, **query):
        c = Client()
        c.force_login(user)
        return c.get(reverse(name), query)

    MONEY_PAGES = ('reports:ar_aging_report', 'reports:mrr_forecast_report',
                   'reports:hardware_margin_report', 'reports:agreement_reconciliation',
                   'reports:psa_profitability_by_client')

    def test_level1_tech_is_refused_money_pages_and_their_csv(self):
        for name in self.MONEY_PAGES:
            with self.subTest(name=name):
                self.assertEqual(self._get(self.l1, name).status_code, 403)
                self.assertEqual(self._get(self.l1, name, format='csv').status_code, 403)

    def test_membership_flag_does_not_unlock_all_customer_profitability(self):
        # Owner of Acme grants reports_view_financial there, but the global
        # role says no: the cross-customer report stays closed.
        r = self._get(self.l1, 'reports:psa_profitability_by_client')
        self.assertEqual(r.status_code, 403)

    def test_finance_role_and_superuser_still_open_them(self):
        for user in (self.finance, self.su):
            for name in self.MONEY_PAGES:
                with self.subTest(user=user.username, name=name):
                    self.assertEqual(self._get(user, name).status_code, 200)

    def test_staff_without_global_role_keep_staff_only_pages(self):
        for name in ('reports:ar_aging_report', 'reports:mrr_forecast_report'):
            with self.subTest(name=name):
                self.assertEqual(self._get(self.legacy, name).status_code, 200)

    def test_kpi_dashboard_hides_recurring_revenue_without_financial_flag(self):
        r = self._get(self.l1, 'reports:kpi_dashboard')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['widgets']['is_staff_view'])
        r = self._get(self.finance, 'reports:kpi_dashboard')
        self.assertTrue(r.context['widgets']['is_staff_view'])

    def test_customer_user_cannot_reach_reports_at_all(self):
        cust = User.objects.create_user('authz_cust', 'c@acme.test', 'pw-authz-123')
        Membership.objects.create(user=cust, organization=self.acme, role=Role.OWNER)
        self.assertEqual(self._get(cust, 'reports:ar_aging_report').status_code, 403)

    def test_scheduled_toggle_refuses_get(self):
        from reports.models import ReportTemplate, ScheduledReport
        tpl = ReportTemplate.objects.create(name='T', report_type='asset_summary',
                                            query_template='', is_global=True)
        sched = ScheduledReport.objects.create(
            name='S', template=tpl, organization=self.acme, frequency='daily',
            delivery_method='download', recipients=[], is_active=True, created_by=self.su)
        Membership.objects.create(user=self.su, organization=self.acme, role=Role.OWNER)
        c = Client()
        c.force_login(self.su)
        r = c.get(reverse('reports:scheduled_toggle', args=[sched.pk]))
        self.assertEqual(r.status_code, 405)
        sched.refresh_from_db()
        self.assertTrue(sched.is_active)
        c.post(reverse('reports:scheduled_toggle', args=[sched.pk]))
        sched.refresh_from_db()
        self.assertFalse(sched.is_active)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GeneratedReportFlagTests(TestCase):
    """A user-activity report is the audit log; generating or downloading it
    needs audit_view for the customer, not just reports_view_dashboards."""

    @classmethod
    def setUpTestData(cls):
        cls.acme = Organization.objects.create(name='Acme', slug='authz-gen-acme')
        cls.tech_role = _role('AuthzGenTech', reports_view_dashboards=True, audit_view=False)
        cls.tech = _staff('authz_gen_tech', cls.tech_role)
        Membership.objects.create(user=cls.tech, organization=cls.acme,
                                  role=Role.READONLY, role_template=cls.tech_role)
        from reports.models import ReportTemplate
        cls.tpl = ReportTemplate.objects.create(
            name='Activity', report_type='user_activity', query_template='', is_global=True)

    def _client(self):
        c = Client()
        c.force_login(self.tech)
        s = c.session
        s['current_organization_id'] = self.acme.pk
        s.save()
        return c

    def test_generate_refused_without_audit_view(self):
        from reports.models import GeneratedReport
        r = self._client().post(reverse('reports:generate_report', args=[self.tpl.pk]),
                                {'format': 'csv'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(GeneratedReport.objects.filter(template=self.tpl).exists())

    def test_download_of_someone_elses_report_refused_without_audit_view(self):
        from django.core.files.base import ContentFile
        from reports.models import GeneratedReport
        gen = GeneratedReport.objects.create(template=self.tpl, organization=self.acme,
                                             format='csv', status='completed')
        gen.file.save('a.csv', ContentFile(b'who,what\n'), save=True)
        c = self._client()
        self.assertEqual(c.get(reverse('reports:generated_download', args=[gen.pk])).status_code, 403)
        self.assertEqual(c.get(reverse('reports:generated_detail', args=[gen.pk])).status_code, 403)

    def test_generate_requires_dashboards_flag(self):
        nobody = _staff('authz_gen_nobody', _role('AuthzNoDash', reports_view_dashboards=False))
        c = Client()
        c.force_login(nobody)
        r = c.get(reverse('reports:generate_report', args=[self.tpl.pk]))
        self.assertEqual(r.status_code, 403)


class ScheduledReportRecheckTests(TestCase):
    """The runner re-checks the schedule's creator at run time."""

    @classmethod
    def setUpTestData(cls):
        cls.acme = Organization.objects.create(name='Acme', slug='authz-sched-acme')

    def _schedule(self, report_type, creator, recipients=None):
        from reports.models import ReportTemplate, ScheduledReport
        tpl = ReportTemplate.objects.create(name=f'T {report_type}', report_type=report_type,
                                            query_template='', is_global=True)
        return ScheduledReport.objects.create(
            name=f'S {report_type}', template=tpl, organization=self.acme, frequency='daily',
            delivery_method='email', recipients=recipients or ['ext@example.com'],
            output_format='csv', created_by=creator,
            next_run=timezone.now() - timedelta(minutes=5))

    def _run(self):
        from django.core.mail import get_connection
        conn = get_connection('django.core.mail.backends.locmem.EmailBackend')
        with mock.patch('core.mailer.get_smtp_connection', return_value=conn):
            call_command('run_scheduled_reports', verbosity=0)

    def test_creator_who_lost_the_permission_gets_nothing_sent(self):
        from django.core import mail
        from reports.models import GeneratedReport
        user = User.objects.create_user('authz_sched_u', 'u@acme.test', 'pw')
        m = Membership.objects.create(user=user, organization=self.acme, role=Role.OWNER)
        sched = self._schedule('user_activity', user)
        m.role = Role.READONLY  # no reports_manage_scheduled, no audit_view
        m.save()
        mail.outbox = []
        self._run()
        gen = GeneratedReport.objects.get(scheduled_report=sched)
        self.assertEqual(gen.status, 'failed')
        self.assertIn('no longer', gen.error_message)
        self.assertEqual(len(mail.outbox), 0)
        sched.refresh_from_db()
        self.assertGreater(sched.next_run, timezone.now())

    def test_deactivated_creator_stops_the_schedule(self):
        from reports.models import GeneratedReport
        user = User.objects.create_user('authz_sched_gone', 'g@acme.test', 'pw')
        Membership.objects.create(user=user, organization=self.acme, role=Role.OWNER)
        sched = self._schedule('asset_summary', user)
        user.is_active = False
        user.save()
        self._run()
        self.assertEqual(GeneratedReport.objects.get(scheduled_report=sched).status, 'failed')

    def test_ownerless_password_audit_is_refused(self):
        from reports.models import GeneratedReport
        sched = self._schedule('password_audit', None)
        self._run()
        gen = GeneratedReport.objects.get(scheduled_report=sched)
        self.assertEqual(gen.status, 'failed')
        self.assertFalse(gen.parameters.get('include_vault'))

    def test_creator_without_vault_view_gets_no_vault_figures(self):
        from reports.models import GeneratedReport
        user = User.objects.create_user('authz_sched_nv', 'nv@acme.test', 'pw')
        role = _role('AuthzSchedNoVault', reports_manage_scheduled=True, org_view_members=True,
                     vault_view=False)
        Membership.objects.create(user=user, organization=self.acme, role=Role.READONLY,
                                  role_template=role)
        sched = self._schedule('organization_metrics', user)
        self._run()
        gen = GeneratedReport.objects.get(scheduled_report=sched)
        self.assertEqual(gen.status, 'completed')
        self.assertIs(gen.parameters.get('include_vault'), False)


class SavedQueryScopeTests(TestCase):
    """Saved queries over invoices and tickets follow the role flags."""

    @classmethod
    def setUpTestData(cls):
        from psa.models import Invoice
        cls.acme = Organization.objects.create(name='Acme', slug='authz-sq-acme')
        Invoice.objects.create(organization=cls.acme, client_org=cls.acme, title='Big',
                               invoice_date=date(2026, 9, 1), total=Decimal('5000'))
        cls.l1 = _staff('authz_sq_l1', _role('AuthzSqL1', billing_view_invoices=False,
                                             tickets_view=False))
        cls.su = User.objects.create_superuser('authz_sq_su', 'su@x.test', 'pw')

    def _run(self, user, target):
        from reports.models import SavedQuery
        from reports.saved_query import execute
        sq = SavedQuery.objects.create(owner=user, name='q', target_model=target)
        _model, qs = execute(sq, user=user)
        return qs

    def test_technician_without_billing_flag_lists_no_invoices(self):
        self.assertEqual(self._run(self.l1, 'psa.Invoice').count(), 0)
        self.assertEqual(self._run(self.su, 'psa.Invoice').count(), 1)

    def test_technician_without_tickets_view_lists_no_tickets(self):
        _setup_seed()
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        Ticket.objects.create(organization=self.acme, subject='Secret', queue=Queue.objects.first(),
                              status=TicketStatus.objects.first(), priority=TicketPriority.objects.first(),
                              ticket_type=TicketType.objects.first())
        self.assertEqual(self._run(self.l1, 'psa.Ticket').count(), 0)
        self.assertEqual(self._run(self.su, 'psa.Ticket').count(), 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WidgetAndWallboardScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        from psa.models import Invoice, Queue, Ticket, TicketPriority, TicketStatus, TicketType
        cls.acme = Organization.objects.create(name='Acme', slug='authz-w-acme')
        cls.other = Organization.objects.create(name='Umbrella', slug='authz-w-umb')
        common = dict(queue=Queue.objects.first(), status=TicketStatus.objects.filter(slug='new').first(),
                      priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first())
        Ticket.objects.create(organization=cls.other, subject='Umbrella secret', **common)
        today = date.today()
        Invoice.objects.create(organization=cls.other, client_org=cls.other, title='T',
                               invoice_date=today, due_date=today, total=900, amount_paid=0,
                               status='sent', subtotal=900, tax_amount=0, currency='USD')
        cls.l1 = _staff('authz_w_l1', _role('AuthzWL1', reports_view_dashboards=True,
                                            reports_view_financial=False, tickets_view=False))
        Membership.objects.create(user=cls.l1, organization=cls.acme, role=Role.OWNER)

    def test_membership_owner_role_does_not_unlock_msp_wide_revenue_widget(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('revenue_this_period', {}, viewer_for(self.l1, is_staff_user=True))
        self.assertTrue(data.get('restricted'))

    def test_ticket_widgets_follow_tickets_view(self):
        from reports.widget_sources import get_widget_data, viewer_for
        data = get_widget_data('open_tickets_count', {}, viewer_for(self.l1, is_staff_user=True))
        self.assertTrue(data.get('restricted'))

    def test_wallboard_data_hides_tickets_without_tickets_view(self):
        c = Client()
        c.force_login(self.l1)
        r = c.get(reverse('reports:wallboard_data'))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['recent_tickets'], [])
        self.assertNotIn('Umbrella secret', r.content.decode())
