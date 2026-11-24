"""Pricing Advisor (Phase 76) tests: detectors, recommendation math, drafts,
OPTIONAL AI narrative validation, permissions and tenant isolation."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from advisor import ai, engine
from advisor.actions import ActionRefused, accept, dismiss, sync_implemented
from advisor.models import AdvisorSettings, Finding, Narrative, Recommendation

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

TODAY = date(2026, 11, 16)           # window (3 months): 2026-08-01 .. 2026-10-31
IN_WINDOW = [date(2026, 8, 12), date(2026, 9, 9), date(2026, 10, 14)]
PRIOR = [date(2026, 5, 12), date(2026, 6, 9), date(2026, 7, 14)]


def _staff(user, role=None):
    from accounts.models import UserProfile, UserType
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    profile.save()
    return user


class AdvisorBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import RoleTemplate
        from core.models import Organization
        from psa.models import Queue, TicketPriority, TicketStatus, TicketType
        from resourcing.models import TechCostRate
        call_command('psa_seed_defaults', verbosity=0)
        cls.a = Organization.objects.create(name='Acme Widgets', slug='adv-acme')
        cls.b = Organization.objects.create(name='Beta Bakery', slug='adv-beta')
        cls.tech = User.objects.create_user('adv_tech', 't@x.com', 'pw')
        TechCostRate.objects.create(user=cls.tech, rate_per_hour=Decimal('50'), effective_from=date(2025, 1, 1))
        cls.norate = User.objects.create_user('adv_norate', 'n@x.com', 'pw')
        cls.role_all = RoleTemplate.objects.create(name='AdvAll', view_profitability=True,
                                                   act_on_pricing_recommendations=True,
                                                   reports_view_financial=True)
        cls.role_view = RoleTemplate.objects.create(name='AdvView', view_profitability=True,
                                                    reports_view_financial=True)
        cls.role_none = RoleTemplate.objects.create(name='AdvNone')
        cls.manager = _staff(User.objects.create_user('adv_mgr', 'm@x.com', 'pw'), cls.role_all)
        cls.viewer = _staff(User.objects.create_user('adv_view', 'v@x.com', 'pw'), cls.role_view)
        cls.plain = _staff(User.objects.create_user('adv_plain', 'p@x.com', 'pw'), cls.role_none)
        cls.base = dict(status=TicketStatus.objects.filter(is_terminal=False).first(),
                        priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
                        queue=Queue.objects.first())

    # -- builders ----------------------------------------------------------

    def ticket(self, org):
        from psa.models import Ticket
        return Ticket.objects.create(organization=org, subject='Work', **self.base)

    def entry(self, org, day, hours, user=None, billable=True, hour=10, ticket=None):
        from psa.models import TicketTimeEntry
        start = timezone.make_aware(datetime(day.year, day.month, day.day, hour, 0))
        return TicketTimeEntry.objects.create(
            ticket=ticket or self.ticket(org), user=user or self.tech, started_at=start,
            ended_at=start + timedelta(minutes=int(hours * 60)), is_billable=billable)

    def invoice(self, org, day, total, contract=None, status='paid'):
        from psa.models import Invoice
        inv = Invoice.objects.create(organization=org, client_org=org, title='Inv', status=status,
                                     invoice_date=day, source_contract=contract)
        Invoice.objects.filter(pk=inv.pk).update(total=Decimal(total), subtotal=Decimal(total))
        return inv

    def contract(self, org, **kw):
        from psa.models import Contract
        data = dict(organization=org, client_org=org, name=f'{org.name} plan', status='active',
                    start_date=date(2026, 1, 1), contract_type='managed_services', billing_frequency='monthly',
                    recurring_amount=Decimal('0'))
        data.update(kw)
        return Contract.objects.create(**data)

    def run_advisor(self, clients=None):
        return engine.run(today=TODAY, clients=clients if clients is not None else [self.a])

    def open_findings(self, detector, org=None):
        return Finding.objects.filter(detector=detector, client_org=org or self.a, status='open')


# --- detectors -------------------------------------------------------------------

class LossMakingTests(AdvisorBase):

    def test_certain_loss_is_raised(self):
        for d in IN_WINDOW:
            self.invoice(self.a, d, '300')
            self.entry(self.a, d, 15)           # 45 h × $50 = $2,250 cost vs $900 revenue
        self.run_advisor()
        f = self.open_findings('loss_making_customer').get()
        self.assertEqual(f.assessment, 'raised')
        self.assertEqual(f.severity, 'critical')
        # Licensing is tracked and this customer has no subscriptions: the cost is known.
        self.assertTrue(f.is_complete)
        self.assertEqual(f.facts['gross_margin']['upper'], '-150.00')
        self.assertTrue(f.recommendations.filter(rec_type__in=['price_increase', 'renegotiate']).exists())

    def test_license_without_unit_cost_makes_the_loss_an_upper_bound(self):
        from licensing.models import LicenseSubscription, SoftwareProduct
        product = SoftwareProduct.objects.create(vendor='Microsoft', name='M365 Business Premium')
        LicenseSubscription.objects.create(organization=self.a, product=product, quantity_purchased=10,
                                           unit_cost=None, status='active')
        for d in IN_WINDOW:
            self.invoice(self.a, d, '300')
            self.entry(self.a, d, 15)
        self.run_advisor()
        f = self.open_findings('loss_making_customer').get()
        self.assertFalse(f.is_complete)          # unknown licence cost is never zero
        self.assertIn('No unit cost', ' '.join(f.missing_inputs))

    def test_profitable_customer_not_raised(self):
        for d in IN_WINDOW:
            self.invoice(self.a, d, '5000')
            self.entry(self.a, d, 2)
        self.run_advisor()
        self.assertFalse(self.open_findings('loss_making_customer').exists())

    def test_unknown_cost_is_flagged_incomplete_not_loss(self):
        for d in IN_WINDOW:
            self.invoice(self.a, d, '300')
            self.entry(self.a, d, 15, user=self.norate)   # no cost rate: labour unknown
        self.run_advisor()
        f = self.open_findings('loss_making_customer').get()
        self.assertEqual(f.assessment, 'incomplete')
        self.assertEqual(f.severity, 'info')
        self.assertFalse(f.is_complete)
        self.assertIn('adv_norate', ' '.join(f.missing_inputs))
        self.assertIsNone(f.facts['labor_cost']['value'])
        self.assertFalse(f.recommendations.exists())


class DecliningMarginTests(AdvisorBase):

    def _setup(self, now_hours):
        for d in PRIOR:
            self.invoice(self.a, d, '1000')
            self.entry(self.a, d, 4)            # $200 / $1000 → 80%
        for d in IN_WINDOW:
            self.invoice(self.a, d, '1000')
            self.entry(self.a, d, now_hours)

    def test_drop_raised(self):
        self._setup(12)                          # $600 / $1000 → 40%
        self.run_advisor()
        f = self.open_findings('declining_margin').get()
        self.assertEqual(f.evidence['drop_pts'], '40.00')
        self.assertTrue(f.is_complete)           # every cost source tracked: gross margin compared

    def test_stable_not_raised(self):
        self._setup(4)
        self.run_advisor()
        self.assertFalse(self.open_findings('declining_margin').exists())


class UnderpricedContractTests(AdvisorBase):

    def _setup(self, hours):
        c = self.contract(self.a, recurring_amount=Decimal('500'))
        for d in IN_WINDOW:
            self.invoice(self.a, d, '500', contract=c)
            self.entry(self.a, d, hours)
        return c

    def test_below_target_rate_raised_with_math(self):
        c = self._setup(10)                       # $1,500 / 30 h = $50/h = cost
        self.run_advisor()
        f = self.open_findings('underpriced_contract').get()
        self.assertEqual(f.subject_key, f'contract:{c.pk}')
        self.assertEqual(f.severity, 'medium')
        rec = f.recommendations.get(rec_type='price_increase')
        # monthly cost $500 ÷ (1 − 35%) = $769.23
        self.assertEqual(rec.proposed['proposed'], '769.23')
        self.assertEqual(rec.proposed['current'], '500.00')
        self.assertEqual(rec.proposed['change'], '269.23')
        self.assertIn('÷ (1 − target margin)', rec.work['formula'])
        self.assertTrue(rec.work['inputs'])
        self.assertTrue(rec.work['assumptions'])

    def test_well_priced_not_raised(self):
        self._setup(1)
        self.run_advisor()
        self.assertFalse(self.open_findings('underpriced_contract').exists())


class AllowanceTests(AdvisorBase):

    def _setup(self, hours):
        c = self.contract(self.a, contract_type='retainer', total_hours=Decimal('10'),
                          recurring_amount=Decimal('1000'))
        for d in IN_WINDOW:
            self.entry(self.a, d, hours)
        return c

    def test_support_over_contract(self):
        c = self._setup(15)
        self.run_advisor()
        f = self.open_findings('support_over_contract').get()
        self.assertEqual(f.severity, 'high')
        rec = f.recommendations.get(rec_type='upsell')
        self.assertEqual(rec.proposed['proposed'], '1500.00')    # 15 h × $100 per included hour
        self.assertEqual(rec.proposed['included_hours'], '15')
        self.assertFalse(self.open_findings('unused_allowance').exists())

    def test_within_allowance_not_over(self):
        self._setup(10)
        self.run_advisor()
        self.assertFalse(self.open_findings('support_over_contract').exists())
        self.assertFalse(self.open_findings('unused_allowance').exists())

    def test_unused_allowance(self):
        self._setup(2)
        self.run_advisor()
        f = self.open_findings('unused_allowance').get()
        self.assertEqual(f.recommendations.get().rec_type, 'bundle_review')


class UnbilledAndLeakageTests(AdvisorBase):

    def test_unbilled_hourly_work(self):
        self.contract(self.a, contract_type='block_hours', billing_frequency='none', hourly_rate=Decimal('100'))
        self.entry(self.a, IN_WINDOW[1], 5)
        self.run_advisor()
        f = self.open_findings('unbilled_work').get()
        self.assertEqual(f.facts['unbilled']['value'], '500.00')

    def test_invoiced_work_not_unbilled(self):
        from psa.models import InvoiceLineItem
        self.contract(self.a, contract_type='block_hours', billing_frequency='none', hourly_rate=Decimal('100'))
        e = self.entry(self.a, IN_WINDOW[1], 5)
        inv = self.invoice(self.a, IN_WINDOW[1], '500')
        InvoiceLineItem.objects.create(invoice=inv, description='t', quantity=5, unit_price=100,
                                       source='time', source_id=str(e.pk))
        self.run_advisor()
        self.assertFalse(self.open_findings('unbilled_work').exists())

    def test_flat_fee_work_is_not_unbilled(self):
        self.contract(self.a, recurring_amount=Decimal('900'))
        self.entry(self.a, IN_WINDOW[1], 5)
        self.run_advisor()
        self.assertFalse(self.open_findings('unbilled_work').exists())
        self.assertFalse(self.open_findings('service_without_charge').exists())

    def test_service_without_charge(self):
        self.entry(self.a, IN_WINDOW[1], 6)
        self.run_advisor()
        f = self.open_findings('service_without_charge').get()
        rec = f.recommendations.get()
        self.assertEqual(rec.rec_type, 'upsell')
        # 6 h × $50 = $300 over 3 months → $100/month ÷ 0.65 = $153.85
        self.assertEqual(rec.proposed['proposed'], '153.85')

    def test_little_uncharged_work_not_raised(self):
        self.entry(self.a, IN_WINDOW[1], 1)
        self.run_advisor()
        self.assertFalse(self.open_findings('service_without_charge').exists())


class RenewalReviewTests(AdvisorBase):

    def _setup(self, days):
        c = self.contract(self.a, recurring_amount=Decimal('300'), end_date=TODAY + timedelta(days=days))
        for d in IN_WINDOW:
            self.invoice(self.a, d, '300', contract=c)
            self.entry(self.a, d, 5)              # $250 cost / $300 → at most 16.67%
        return c

    def test_renewal_with_low_margin(self):
        c = self._setup(75)
        self.run_advisor()
        f = self.open_findings('renewal_review').get()
        self.assertEqual(f.subject_key, f'contract:{c.pk}')
        self.assertTrue(f.recommendations.exists())

    def test_renewal_outside_window(self):
        self._setup(200)
        self.run_advisor()
        self.assertFalse(self.open_findings('renewal_review').exists())


class PricingDependentDetectorTests(AdvisorBase):

    def _item(self, cost, price):
        from pricing.models import CustomerPriceOverride, PriceBook, PriceBookItem
        book = PriceBook.objects.create(name='Book')
        item = PriceBookItem.objects.create(price_book=book, name='Backup seat', sku='BK1', cost=Decimal(cost),
                                            default_price=Decimal(price))
        CustomerPriceOverride.objects.create(client_org=self.a, item=item, unit_price=Decimal(price))
        return item

    def test_cost_increase_not_passed_through(self):
        from pricing.models import PriceChangeHistory
        item = self._item('10', '20')
        item.cost = Decimal('12')
        item.save()
        self.assertTrue(PriceChangeHistory.objects.filter(price_book_item=item, field='cost').exists())
        # The run is pinned to TODAY; date the change inside its window, not at
        # the wall-clock time the test happens to run.
        at = lambda days: timezone.make_aware(datetime.combine(TODAY - timedelta(days=days), time(12)))
        PriceChangeHistory.objects.filter(price_book_item=item).update(changed_at=at(10))
        PriceChangeHistory.objects.filter(price_book_item=item, field='cost').update(changed_at=at(5))
        self.run_advisor()
        f = self.open_findings('cost_increase_not_passed_through').get()
        rec = f.recommendations.get()
        self.assertEqual(rec.proposed['proposed'], '24.00')   # $20 × 12 ÷ 10

    def test_cost_increase_with_price_change_not_raised(self):
        item = self._item('10', '20')
        item.cost = Decimal('12')
        item.default_price = Decimal('24')
        item.save()
        from pricing.models import PriceChangeHistory
        PriceChangeHistory.objects.filter(price_book_item=item).update(
            changed_at=timezone.make_aware(datetime.combine(TODAY - timedelta(days=5), time(12))))
        self.run_advisor()
        self.assertFalse(self.open_findings('cost_increase_not_passed_through').exists())

    def _plans(self, hours):
        from pricing.models import ClientServicePlan, ServicePlan
        small = ServicePlan.objects.create(name='Small', included_support_hours=Decimal('5'),
                                           monthly_price=Decimal('500'))
        ServicePlan.objects.create(name='Large', included_support_hours=Decimal('20'), monthly_price=Decimal('1500'))
        ClientServicePlan.objects.create(client_org=self.a, plan=small, start_date=date(2026, 1, 1),
                                         status='active')
        for d in IN_WINDOW:
            self.entry(self.a, d, hours)

    def test_tier_fit(self):
        self._plans(10)
        self.run_advisor()
        f = self.open_findings('tier_fit').get()
        rec = f.recommendations.get()
        self.assertEqual(rec.rec_type, 'tier_change')
        self.assertEqual(rec.proposed['proposed'], '1500.00')

    def test_tier_fit_not_raised_when_within_plan(self):
        self._plans(4)
        self.run_advisor()
        self.assertFalse(self.open_findings('tier_fit').exists())

    def test_cost_detector_not_evaluated_without_history(self):
        with mock.patch('advisor.inputs.cost_history_available', return_value=False):
            cov = engine.coverage()
        self.assertFalse(cov['cost_increase_not_passed_through']['evaluated'])
        self.assertIn('Not evaluated', cov['cost_increase_not_passed_through']['reason'])


# --- idempotency, thresholds -----------------------------------------------------------

class EngineTests(AdvisorBase):

    def test_idempotent_and_versioned(self):
        self.entry(self.a, IN_WINDOW[1], 6)
        self.run_advisor()
        self.run_advisor()
        f = self.open_findings('service_without_charge').get()
        self.assertEqual(f.version, 1)
        self.entry(self.a, IN_WINDOW[2], 2)
        self.run_advisor()
        f.refresh_from_db()
        self.assertEqual(self.open_findings('service_without_charge').count(), 1)
        self.assertEqual(f.version, 2)

    def test_resolved_when_no_longer_detected(self):
        e = self.entry(self.a, IN_WINDOW[1], 6)
        self.run_advisor()
        e.delete()
        self.run_advisor()
        self.assertEqual(Finding.objects.get(detector='service_without_charge').status, 'resolved')

    def test_per_customer_threshold(self):
        self.entry(self.a, IN_WINDOW[1], 6)
        AdvisorSettings.objects.create(organization=self.a, leakage_min_hours=Decimal('10'))
        self.run_advisor()
        self.assertFalse(self.open_findings('service_without_charge').exists())

    def test_disabled_detector(self):
        self.entry(self.a, IN_WINDOW[1], 6)
        AdvisorSettings.objects.create(organization=None, disabled_detectors=['service_without_charge'])
        self.run_advisor()
        self.assertFalse(self.open_findings('service_without_charge').exists())

    def test_command_and_scheduler_registration(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['run_advisor'], ('run_advisor', []))
        self.assertIn('run_advisor', dict(ScheduledTask.TASK_TYPES))
        self.assertIn('run_advisor', {d['task_type'] for d in ScheduledTask.PERIODIC_COMMAND_DEFAULTS})
        self.entry(self.a, IN_WINDOW[1], 6)
        from io import StringIO
        out = StringIO()
        call_command('run_advisor', '--today', TODAY.isoformat(), '--customer', str(self.a.pk), stdout=out)
        self.assertIn('1 customer', out.getvalue())


# --- accept / dismiss / implemented --------------------------------------------------------

class ActionTests(AdvisorBase):

    def _underpriced(self):
        c = self.contract(self.a, recurring_amount=Decimal('500'))
        for d in IN_WINDOW:
            self.invoice(self.a, d, '500', contract=c)
            self.entry(self.a, d, 10)
        self.run_advisor()
        return c, Recommendation.objects.get(rec_type='price_increase', contract=c,
                                             finding__detector='underpriced_contract')

    def test_accept_creates_draft_contract_only(self):
        from audit.models import AuditLog
        from psa.models import Contract
        c, rec = self._underpriced()
        before = Contract.objects.filter(pk=c.pk).values().get()
        rec = accept(rec, self.manager)
        self.assertEqual(rec.status, 'accepted')
        draft = rec.draft_contract
        self.assertEqual(draft.status, 'draft')
        self.assertEqual(draft.recurring_amount, Decimal('769.23'))
        self.assertIsNone(draft.parent_contract_id)
        after = Contract.objects.filter(pk=c.pk).values().get()
        self.assertEqual(before, after)          # the active contract is untouched
        self.assertTrue(AuditLog.objects.filter(extra_data__event='advisor_recommendation_accepted').exists())
        with self.assertRaises(ActionRefused):
            accept(rec, self.manager)

    def test_accept_quote_path(self):
        self.entry(self.a, IN_WINDOW[1], 6)
        self.run_advisor()
        rec = Recommendation.objects.get(finding__detector='service_without_charge')
        rec = accept(rec, self.manager)
        self.assertEqual(rec.draft_quote.status, 'draft')
        self.assertEqual(rec.draft_quote.client_org, self.a)
        self.assertEqual(rec.draft_quote.total, Decimal('153.85'))

    def test_implemented_when_draft_activated(self):
        _c, rec = self._underpriced()
        rec = accept(rec, self.manager)
        sync_implemented()
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'accepted')
        rec.draft_contract.status = 'active'
        rec.draft_contract.save()
        sync_implemented()
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'implemented')

    def test_accept_needs_permission(self):
        _c, rec = self._underpriced()
        with self.assertRaises(ActionRefused):
            accept(rec, self.viewer)
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'open')

    def test_dismiss_needs_reason(self):
        _c, rec = self._underpriced()
        with self.assertRaises(ActionRefused):
            dismiss(rec, self.manager, '  ')
        rec = dismiss(rec, self.manager, 'Strategic account')
        self.assertEqual(rec.status, 'dismissed')
        self.assertEqual(rec.dismiss_reason, 'Strategic account')

    def test_rerun_keeps_decided_recommendation(self):
        _c, rec = self._underpriced()
        dismiss(rec, self.manager, 'No')
        self.run_advisor()
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'dismissed')


# --- OPTIONAL AI ---------------------------------------------------------------------------

class NarrativeTests(AdvisorBase):

    def setUp(self):
        self.entry(self.a, IN_WINDOW[1], 6)
        self.run_advisor()
        self.finding = self.open_findings('service_without_charge').get()

    def _ai_on(self, on=True):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.psa_ai_enabled = on
        s.save()

    def test_payload_has_no_customer_name_and_labels_basis(self):
        payload = ai.build_payload(self.finding)
        text = str(payload)
        self.assertNotIn('Acme Widgets', text)
        self.assertTrue(all(f['status'] in ('verified', 'estimate', 'unknown', 'not applicable')
                            for f in payload['facts']))

    def test_validate(self):
        payload = ai.build_payload(self.finding)
        ok, bad = ai.validate('About 6.00 hours were uncharged; a $153.85 agreement at 35% margin.', payload)
        self.assertTrue(ok, bad)
        ok, bad = ai.validate('This costs you $9,999 a year, a 12% loss.', payload)
        self.assertFalse(ok)
        self.assertIn('$9,999', bad)

    @mock.patch('psa_ai.permissions.has_capability', return_value=True)
    def test_valid_narrative_accepted_and_cached(self, _cap):
        self._ai_on()
        with mock.patch('advisor.ai._call_model', return_value=('Uncharged work: a $153.85 agreement.', 'x/y')) as call:
            n = ai.explain(self.finding, self.manager)
            ai.explain(self.finding, self.manager)
        self.assertEqual(n.status, 'accepted')
        self.assertEqual(call.call_count, 1)
        sent = call.call_args[0][2]
        self.assertNotIn('Acme Widgets', str(sent))

    @mock.patch('psa_ai.permissions.has_capability', return_value=True)
    def test_invented_number_rejected(self, _cap):
        self._ai_on()
        with mock.patch('advisor.ai._call_model', return_value=('You lose $4,200 a year.', 'x/y')):
            n = ai.explain(self.finding, self.manager)
        self.assertEqual(n.status, 'rejected')
        self.assertEqual(n.text, '')
        self.assertIn('$4,200', n.rejected_figures)

    @mock.patch('psa_ai.permissions.has_capability', return_value=True)
    def test_ai_disabled_no_call(self, _cap):
        self._ai_on(False)
        with mock.patch('advisor.ai._call_model') as call:
            with self.assertRaises(ai.NarrativeRefused):
                ai.explain(self.finding, self.manager)
        call.assert_not_called()
        self.assertFalse(Narrative.objects.exists())

    @mock.patch('psa_ai.permissions.has_capability', return_value=True)
    def test_ai_never_creates_drafts(self, _cap):
        self._ai_on()
        with mock.patch('advisor.ai._call_model', return_value=('Fine.', 'x/y')):
            ai.explain(self.finding, self.manager)
        self.assertFalse(Recommendation.objects.exclude(status='open').exists())


# --- views, permissions, isolation ------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(AdvisorBase):

    def setUp(self):
        self.entry(self.a, IN_WINDOW[1], 6)
        self.entry(self.b, IN_WINDOW[1], 6)
        engine.run(today=TODAY, clients=[self.a, self.b])
        self.fa = self.open_findings('service_without_charge', self.a).get()
        self.fb = self.open_findings('service_without_charge', self.b).get()

    def test_list_and_detail_render_with_banner(self):
        self.client.force_login(self.manager)
        r = self.client.get(reverse('advisor:finding_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'not your accounting P&amp;L')
        self.assertContains(r, self.fa.title)
        self.assertContains(r, 'Detector coverage')
        r = self.client.get(reverse('advisor:finding_detail', args=[self.fa.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Show the work')
        self.assertContains(r, 'Accept — create a draft')
        self.assertNotContains(r, 'Explain in plain English')   # AI off by default
        r = self.client.get(reverse('advisor:client_facts', args=[self.a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Trailing 12 months')

    def test_viewer_sees_but_cannot_act(self):
        self.client.force_login(self.viewer)
        r = self.client.get(reverse('advisor:finding_detail', args=[self.fa.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Accept — create a draft')
        rec = self.fa.recommendations.get()
        r = self.client.post(reverse('advisor:recommendation_accept', args=[rec.pk]))
        self.assertEqual(r.status_code, 403)
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'open')

    def test_accept_via_view(self):
        self.client.force_login(self.manager)
        rec = self.fa.recommendations.get()
        r = self.client.post(reverse('advisor:recommendation_accept', args=[rec.pk]))
        self.assertEqual(r.status_code, 302)
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'accepted')
        self.assertIsNotNone(rec.draft_quote_id)

    def test_staff_without_permission_denied(self):
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get(reverse('advisor:finding_list')).status_code, 403)

    def test_tenant_isolation_by_client_scope(self):
        scoped = _staff(User.objects.create_user('adv_scoped', 's@x.com', 'pw'), self.role_all)
        profile = scoped.profile
        profile.client_scope = 'selected'
        profile.save()
        profile.scope_organizations.add(self.a)
        self.client.force_login(scoped)
        r = self.client.get(reverse('advisor:finding_list'))
        self.assertContains(r, self.fa.title)
        self.assertNotContains(r, self.fb.title)
        self.assertEqual(self.client.get(reverse('advisor:finding_detail', args=[self.fb.pk])).status_code, 404)
        rec = self.fb.recommendations.get()
        self.assertEqual(self.client.post(reverse('advisor:recommendation_accept', args=[rec.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('advisor:client_facts', args=[self.b.pk])).status_code, 404)

    def test_customer_user_never_sees_advisor(self):
        from accounts.models import Membership
        cust = User.objects.create_user('adv_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=cust, organization=self.a, role='owner', role_template=self.role_all,
                                  is_active=True)
        self.client.force_login(cust)
        self.assertIn(self.client.get(reverse('advisor:finding_list')).status_code, (403, 404))
        self.assertIn(self.client.get(reverse('advisor:finding_detail', args=[self.fa.pk])).status_code, (403, 404))
        self.assertIn(self.client.get(reverse('advisor:client_facts', args=[self.a.pk])).status_code, (403, 404))
        from django.template import Context, Template
        from django.test import RequestFactory
        req = RequestFactory().get('/')
        req.user = cust
        html = Template('{% load advisor_tags %}{% org_advisor org %}').render(Context({'request': req, 'org': self.a}))
        self.assertNotIn('Pricing Advisor', html)

    def test_workspace_panel_for_staff(self):
        from django.template import Context, Template
        from django.test import RequestFactory
        req = RequestFactory().get('/')
        req.user = self.manager
        html = Template('{% load advisor_tags %}{% org_advisor org %}').render(Context({'request': req, 'org': self.a}))
        self.assertIn('Pricing Advisor', html)
        self.assertIn('not your accounting P&amp;L', html)

    def test_explain_refused_when_ai_off(self):
        self.client.force_login(self.manager)
        with mock.patch('advisor.ai._call_model') as call:
            r = self.client.post(reverse('advisor:finding_explain', args=[self.fa.pk]))
        self.assertEqual(r.status_code, 403)
        call.assert_not_called()

    def test_settings_pages(self):
        self.client.force_login(self.manager)
        url = reverse('advisor:settings') + f'?client={self.a.pk}'
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {'client': self.a.pk, 'target_margin_pct': '40', 'lookback_months': '6',
                                   **{f'detector_{k}': 'on' for k in ('loss_making_customer',)}})
        self.assertEqual(r.status_code, 302)
        row = AdvisorSettings.objects.get(organization=self.a)
        self.assertEqual(row.target_margin_pct, Decimal('40'))
        self.assertIn('unbilled_work', row.disabled_detectors)
        # install-wide defaults: superusers only
        self.assertEqual(self.client.get(reverse('advisor:settings')).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_nav_link(self):
        from core.navigation import SECTIONS_BY_KEY
        tabs = [t.url_name for t in SECTIONS_BY_KEY['mod_reports'].tabs]
        self.assertIn('advisor:finding_list', tabs)
