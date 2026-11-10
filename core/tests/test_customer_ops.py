"""Customer operations page (core/customer_ops.py).

Pins each section's data (what counts as an SLA risk, an uptime incident, a
renewal, an overdue invoice and an aging asset), and that totals and
drill-downs follow the user's role for *that* customer: a section is neither
computed nor shown without its flag, customer users see only their own
customer, and nothing from another customer is ever counted.
"""
import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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


def _block(html, key):
    """The HTML of one section card on the page."""
    m = re.search(r'id="ops-%s"(.*?)(?=id="ops-|\Z)' % key, html, re.S)
    return m.group(1) if m else ''


def _total(html, key):
    m = re.search(r'data-total="%s">(\d+)' % key, html)
    return int(m.group(1)) if m else None


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerOpsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, RoleTemplate
        from assets.models import Asset
        from core.models import Organization, SystemSetting
        from monitoring.models import MonitorCheck, WebsiteMonitor
        from psa.models import (Contract, Invoice, Queue, Ticket, TicketPriority,
                                TicketStatus, TicketType)
        from statuspage.models import StatusPage, StatusPageIncident

        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.monitoring_enabled = True
        s.save()

        cls.a = Organization.objects.create(name='Acme Ops', slug='acme-ops')
        cls.b = Organization.objects.create(name='Other Ops', slug='other-ops')
        now = timezone.now()
        today = timezone.localdate()

        # -- tickets ------------------------------------------------------
        open_status = TicketStatus.objects.filter(is_terminal=False, pauses_sla=False).first()
        base = dict(status=open_status, priority=TicketPriority.objects.first(),
                    ticket_type=TicketType.objects.first(), queue=Queue.objects.first())

        def ticket(org, subject, created, due, shared=False):
            t = Ticket.objects.create(organization=org, subject=subject, **base)
            Ticket.objects.filter(pk=t.pk).update(
                created_at=created, resolution_due_at=due, first_response_due_at=None,
                first_response_at=created, client_can_view=shared)
            return Ticket.objects.get(pk=t.pk)

        cls.breached = ticket(cls.a, 'Breached printer', now - timedelta(hours=10), now - timedelta(hours=1))
        cls.warning = ticket(cls.a, 'Nearly due VPN', now - timedelta(hours=9), now + timedelta(hours=1),
                             shared=True)
        cls.on_track = ticket(cls.a, 'Fine ticket', now - timedelta(hours=1), now + timedelta(hours=9))
        ticket(cls.b, 'Other breached', now - timedelta(hours=10), now - timedelta(hours=1), shared=True)

        # -- monitors / incidents ----------------------------------------
        cls.down = WebsiteMonitor.objects.create(organization=cls.a, name='Shop site', url='https://a.example',
                                                 status='down')
        recovered = WebsiteMonitor.objects.create(organization=cls.a, name='Blog', url='https://b.example',
                                                  status='active')
        MonitorCheck.objects.create(monitor=recovered, checked_at=now - timedelta(days=1), status='down')
        old = WebsiteMonitor.objects.create(organization=cls.a, name='Old outage', url='https://c.example',
                                            status='active')
        MonitorCheck.objects.create(monitor=old, checked_at=now - timedelta(days=30), status='down')
        WebsiteMonitor.objects.create(organization=cls.b, name='Other site', url='https://o.example',
                                      status='down')
        page = StatusPage.objects.create(title='Acme status', organization=cls.a, is_enabled=True)
        StatusPageIncident.objects.create(page=page, title='Email delays', started_at=now - timedelta(hours=2))
        StatusPageIncident.objects.create(page=page, title='Draft incident', started_at=now - timedelta(hours=2),
                                          is_published=False)

        # -- contracts ----------------------------------------------------
        def contract(org, name, status, end, **kw):
            return Contract.objects.create(organization=org, client_org=org, name=name, status=status,
                                           start_date=today - timedelta(days=365), end_date=end, **kw)

        contract(cls.a, 'Ending soon', 'active', today + timedelta(days=10))
        contract(cls.a, 'Lapsed', 'expired', today - timedelta(days=20))
        renewed = contract(cls.a, 'Renewed one', 'expired', today - timedelta(days=5))
        contract(cls.a, 'Next period', 'active', today + timedelta(days=360), parent_contract=renewed)
        contract(cls.a, 'Far away', 'active', today + timedelta(days=200))
        contract(cls.b, 'Other ending', 'active', today + timedelta(days=5))

        # -- invoices -----------------------------------------------------
        def invoice(org, title, status, due, total, paid=0, currency='USD'):
            inv = Invoice.objects.create(organization=org, client_org=org, title=title, status=status,
                                         invoice_date=today - timedelta(days=60), due_date=due,
                                         currency=currency)
            Invoice.objects.filter(pk=inv.pk).update(total=Decimal(total), amount_paid=Decimal(paid))
            return inv

        cls.overdue = invoice(cls.a, 'Overdue one', 'sent', today - timedelta(days=40), '100.00')
        invoice(cls.a, 'Part paid', 'partial', today - timedelta(days=5), '50.00', paid='20.00')
        invoice(cls.a, 'Paid', 'paid', today - timedelta(days=40), '75.00', paid='75.00')
        invoice(cls.a, 'Not due', 'sent', today + timedelta(days=10), '30.00')
        invoice(cls.a, 'Draft', 'draft', today - timedelta(days=40), '30.00')
        invoice(cls.b, 'Other overdue', 'overdue', today - timedelta(days=40), '999.00')

        # -- assets -------------------------------------------------------
        cls.expired_asset = Asset.objects.create(organization=cls.a, name='Old server',
                                                 warranty_expiry=today - timedelta(days=3))
        Asset.objects.create(organization=cls.a, name='EOL switch',
                             vendor_end_of_life=today + timedelta(days=30))
        Asset.objects.create(organization=cls.a, name='Unsupported fw',
                             vendor_end_of_support=today - timedelta(days=1))
        Asset.objects.create(organization=cls.a, name='Healthy laptop',
                             warranty_expiry=today + timedelta(days=500))
        Asset.objects.create(organization=cls.a, name='Aged desktop',
                             purchase_date=today - timedelta(days=365 * 8))
        Asset.objects.create(organization=cls.b, name='Other server',
                             warranty_expiry=today - timedelta(days=3))

        # -- users --------------------------------------------------------
        cls.su = User.objects.create_superuser('ops_su', 'su@x.com', 'pw')
        cls.tech = _make_msp_tech(User.objects.create_user('ops_tech', 't@x.com', 'pw'))
        cls.owner = User.objects.create_user('ops_owner', 'o@x.com', 'pw')
        Membership.objects.create(user=cls.owner, organization=cls.a, role='owner')
        cls.limited = User.objects.create_user('ops_limited', 'l@x.com', 'pw')
        cls.limited_role = RoleTemplate.objects.create(
            name='Ops limited', tickets_view=True, assets_view=True, monitoring_view=True,
            billing_view_invoices=False, reports_view_financial=False)
        Membership.objects.create(user=cls.limited, organization=cls.a, role='readonly',
                                  role_template=cls.limited_role)
        cls.other = User.objects.create_user('ops_other', 'x@x.com', 'pw')
        Membership.objects.create(user=cls.other, organization=cls.b, role='owner')

    def _get(self, user, url, org=None):
        self.client.force_login(user)
        if org is not None:
            session = self.client.session
            session['current_organization_id'] = org.pk
            session.save()
        return self.client.get(url)

    def page(self, org=None):
        return reverse('core:customer_ops', args=[(org or self.a).pk])

    def section_url(self, key, org=None):
        return reverse('core:customer_ops_section', args=[(org or self.a).pk, key])

    def build(self, user, key, org=None):
        from core import customer_ops
        return customer_ops.build_section(SimpleNamespace(user=user, is_staff_user=False), org or self.a, key)

    # -- section data ----------------------------------------------------

    def test_sla_section_lists_breached_and_warning_open_tickets_only(self):
        s = self.build(self.su, 'sla')
        titles = [i.title for i in s.items]
        self.assertEqual(len(titles), 2)
        self.assertIn(self.breached.ticket_number, titles[0])          # breached first
        self.assertEqual(s.items[0].severity, 'danger')
        self.assertIn(self.warning.ticket_number, titles[1])
        self.assertFalse(any('Fine ticket' in t or 'Other' in t for t in titles))
        self.assertEqual(s.items[0].actions[0].url,
                         reverse('psa:ticket_detail', args=[self.breached.ticket_number]))

    def test_uptime_section_down_monitor_recent_outage_and_incidents(self):
        s = self.build(self.su, 'uptime')
        titles = {i.title for i in s.items}
        self.assertEqual(titles, {'Shop site', 'Blog', 'Email delays', 'Draft incident'})
        down = next(i for i in s.items if i.title == 'Shop site')
        self.assertEqual(down.severity, 'danger')
        self.assertIn(reverse('monitoring:website_monitor_detail', args=[self.down.pk]),
                      [a.url for a in down.actions])

    def test_uptime_section_hides_unpublished_incidents_from_customer_users(self):
        titles = {i.title for i in self.build(self.limited, 'uptime').items}
        self.assertIn('Email delays', titles)
        self.assertNotIn('Draft incident', titles)

    def test_renewals_section(self):
        s = self.build(self.su, 'renewals')
        names = [i.title for i in s.items]
        self.assertEqual(names, ['Lapsed', 'Ending soon'])   # ended first, renewed + far excluded
        self.assertEqual(s.items[0].severity, 'danger')

    def test_invoices_section_and_amount(self):
        s = self.build(self.su, 'invoices')
        self.assertEqual(len(s.items), 2)
        self.assertEqual(s.amounts, [('USD', Decimal('130.00'))])   # 100 + (50 - 20)
        self.assertTrue(s.items[0].title.startswith(self.overdue.invoice_number))
        labels = [a.label for a in s.items[0].actions]
        self.assertEqual(labels, ['Open invoice', 'Send reminder'])

    def test_assets_section(self):
        s = self.build(self.su, 'assets')
        self.assertEqual({i.title for i in s.items}, {'Old server', 'EOL switch', 'Unsupported fw'})
        old = next(i for i in s.items if i.title == 'Old server')
        self.assertEqual(old.severity, 'danger')
        plan = next(a for a in old.actions if a.label == 'Plan replacement')
        self.assertIn(f'asset={self.expired_asset.pk}', plan.url)

    def test_assets_age_warning_only_when_setting_is_on(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.asset_age_warnings_enabled = True
        s.save()
        titles = {i.title for i in self.build(self.su, 'assets').items}
        self.assertIn('Aged desktop', titles)

    # -- page, totals and gates -------------------------------------------

    def test_superuser_sees_every_section_with_totals(self):
        r = self._get(self.su, self.page())
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertEqual(_total(html, 'sla'), 2)
        self.assertEqual(_total(html, 'uptime'), 4)
        self.assertEqual(_total(html, 'renewals'), 2)
        self.assertEqual(_total(html, 'invoices'), 2)
        self.assertEqual(_total(html, 'assets'), 3)
        self.assertIn('USD 130.00', html)
        self.assertNotIn('USD 999', html)                 # the other customer's invoice
        self.assertNotIn('Other overdue', html)
        self.assertNotIn('Other breached', html)
        self.assertNotIn('Other server', html)

    def test_msp_tech_without_global_role_sees_every_section(self):
        html = self._get(self.tech, self.page()).content.decode()
        for key in ('sla', 'uptime', 'renewals', 'invoices', 'assets'):
            self.assertIsNotNone(_total(html, key), key)

    def test_msp_tech_global_role_without_billing_sees_no_invoices(self):
        from accounts.models import RoleTemplate
        role = RoleTemplate.objects.create(name='Tech global', tickets_view=True, assets_view=True,
                                           monitoring_view=True)
        _make_msp_tech(self.tech, global_role=role)
        html = self._get(self.tech, self.page()).content.decode()
        self.assertIsNone(_total(html, 'invoices'))
        self.assertIsNone(_total(html, 'renewals'))
        self.assertIsNotNone(_total(html, 'sla'))
        self.assertEqual(self._get(self.tech, self.section_url('invoices')).status_code, 403)

    def test_user_without_financial_permission_sees_no_invoice_total_or_drilldown(self):
        r = self._get(self.limited, self.page(), org=self.a)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIsNone(_total(html, 'invoices'))
        self.assertIsNone(_total(html, 'renewals'))
        self.assertNotIn('USD', html)
        self.assertNotIn(self.overdue.invoice_number, html)
        self.assertNotIn('Lapsed', html)
        self.assertEqual(self._get(self.limited, self.section_url('invoices')).status_code, 403)
        self.assertEqual(self._get(self.limited, self.section_url('renewals')).status_code, 403)

    def test_customer_user_sees_only_tickets_shared_with_them(self):
        html = self._get(self.limited, self.page(), org=self.a).content.decode()
        self.assertEqual(_total(html, 'sla'), 1)
        self.assertIn('Nearly due VPN', html)
        self.assertNotIn('Breached printer', html)

    def test_customer_owner_gets_financial_sections_without_staff_links(self):
        html = self._get(self.owner, self.page(), org=self.a).content.decode()
        self.assertEqual(_total(html, 'invoices'), 2)
        self.assertEqual(_total(html, 'renewals'), 2)
        sections = _block(html, 'renewals') + _block(html, 'invoices') + _block(html, 'uptime')
        self.assertIn('Lapsed', sections)
        self.assertNotIn('/psa/contracts/', sections)
        self.assertNotIn('/psa/invoices/', sections)
        self.assertNotIn('/status/', sections)

    def test_other_customer_page_and_drilldowns_are_404(self):
        self.assertEqual(self._get(self.other, self.page(self.a), org=self.b).status_code, 404)
        for key in ('sla', 'uptime', 'renewals', 'invoices', 'assets'):
            self.assertEqual(self._get(self.other, self.section_url(key, self.a)).status_code, 404, key)
        self.assertEqual(self._get(self.limited, self.page(self.b), org=self.a).status_code, 404)

    def test_unknown_section_is_404(self):
        self.assertEqual(self._get(self.su, self.section_url('payroll')).status_code, 404)

    def test_drilldown_lists_section(self):
        r = self._get(self.su, self.section_url('assets'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_total(r.content.decode(), 'assets'), 3)

    def test_psa_off_hides_psa_sections(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        html = self._get(self.su, self.page()).content.decode()
        self.assertIsNone(_total(html, 'sla'))
        self.assertIsNone(_total(html, 'invoices'))
        self.assertIsNone(_total(html, 'renewals'))
        self.assertIsNotNone(_total(html, 'assets'))
        self.assertEqual(self._get(self.su, self.section_url('sla')).status_code, 403)

    def test_monitoring_off_hides_uptime(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.monitoring_enabled = False
        s.save()
        self.assertIsNone(_total(self._get(self.su, self.page()).content.decode(), 'uptime'))

    def test_viewing_another_customer_switches_the_session(self):
        self._get(self.tech, self.page(self.a), org=self.b)
        self.assertEqual(self.client.session['current_organization_id'], self.a.pk)

    def test_global_view_is_left_alone(self):
        self.client.force_login(self.tech)
        session = self.client.session
        session['global_view_mode'] = True
        session.save()
        self.assertEqual(self.client.get(self.page(self.b)).status_code, 200)
        self.assertIsNone(self.client.session.get('current_organization_id'))

    def test_current_redirects_to_current_customer(self):
        r = self._get(self.limited, reverse('core:customer_ops_current'), org=self.a)
        self.assertRedirects(r, self.page(self.a), fetch_redirect_response=False)

    def test_reachable_from_customer_page_and_switcher(self):
        html = self._get(self.owner, reverse('accounts:organization_detail', args=[self.a.pk]),
                         org=self.a).content.decode()
        self.assertIn(self.page(self.a), html)
        self.assertIn('data-nav="customer-ops"', html)

    def test_ticket_create_prefills_asset_from_plan_replacement(self):
        url = reverse('psa:ticket_create') + f'?asset={self.expired_asset.pk}&subject=Plan+replacement'
        r = self._get(self.su, url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['preselected_asset_id'], self.expired_asset.pk)
        self.assertEqual(r.context['preselected_client_id'], self.a.pk)
        self.assertEqual(r.context['prefill_subject'], 'Plan replacement')

    def test_ticket_create_ignores_asset_of_customer_user_cannot_file_for(self):
        from assets.models import Asset
        other_asset = Asset.objects.get(name='Other server')
        r = self._get(self.owner, reverse('psa:ticket_create') + f'?asset={other_asset.pk}', org=self.a)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['preselected_asset_id'])
