"""
CRM tests — Phases 5.1 + 5.2.

Covers:
* Lead.contact_full_name
* Opportunity.weighted_value
* Pipeline kanban view auth
* Lead → Org + Opportunity conversion
* Permission gating on /crm/pipeline/
* CommissionRule matching + computation (5.2)
* Commission engine idempotence (5.2)
* Lead scoring heuristic (5.2)
* Sales funnel query shape + math (5.2)
* /crm/commissions/ permission gating (5.2)

Tests run with REQUIRE_2FA=False + SECURE_SSL_REDIRECT=False (matching
resourcing's pattern) so the SSL/2FA middleware doesn't 30x the test
client. Sessions also pre-set `2fa_prompted=True` to bypass the
optional-2FA prompt redirect.

Phase 5.2 also strips Enforce2FAMiddleware and AxesMiddleware via the
TEST_MIDDLEWARE list so the test client can hit /crm/commissions/ without
extra redirects.
"""
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse


User = get_user_model()


# Strip Axes + 2FA middleware for view-level tests in Phase 5.2.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _bypass_2fa(client):
    """Pre-set 2fa_prompted on the session so Enforce2FAMiddleware passes."""
    session = client.session
    session['2fa_prompted'] = True
    session.save()


class LeadModelTests(TestCase):
    def test_contact_full_name(self):
        from crm.models import Lead
        from core.models import Organization
        org = Organization.objects.create(name='X', slug='x')
        l = Lead(
            organization=org, company_name='Acme',
            contact_first_name='Wile', contact_last_name='Coyote',
        )
        self.assertEqual(l.contact_full_name, 'Wile Coyote')

    def test_contact_full_name_only_first(self):
        from crm.models import Lead
        from core.models import Organization
        org = Organization.objects.create(name='Y', slug='y')
        l = Lead(organization=org, company_name='B', contact_first_name='Solo')
        self.assertEqual(l.contact_full_name, 'Solo')


class OpportunityWeightingTests(TestCase):
    def test_weighted_value_calculation(self):
        from crm.models import Opportunity
        from core.models import Organization
        msp = Organization.objects.create(name='MSP', slug='msp')
        cl = Organization.objects.create(name='Cl', slug='cl')
        o = Opportunity(
            organization=msp, client_org=cl, name='Test',
            estimated_value=10000, probability_pct=25,
        )
        self.assertEqual(float(o.weighted_value), 2500.0)

    def test_is_open_property(self):
        from crm.models import Opportunity
        from core.models import Organization
        msp = Organization.objects.create(name='MSP2', slug='msp2')
        cl = Organization.objects.create(name='Cl2', slug='cl2')
        o = Opportunity(
            organization=msp, client_org=cl, name='Live',
            stage='proposal',
        )
        self.assertTrue(o.is_open)
        o.stage = 'closed_won'
        self.assertFalse(o.is_open)


@override_settings(REQUIRE_2FA=False, SECURE_SSL_REDIRECT=False)
class PipelineKanbanViewTests(TestCase):
    """Renders for users with crm_manage_pipeline (superuser passes)."""

    def setUp(self):
        from core.models import Organization
        self.org = Organization.objects.create(name='MSP3', slug='msp3')
        self.client_obj = Client()

    def test_anonymous_redirected(self):
        url = reverse('crm:pipeline')
        resp = self.client_obj.get(url)
        # login_required should redirect to login
        self.assertIn(resp.status_code, (302, 301))

    def test_superuser_sees_kanban(self):
        u = User.objects.create_superuser(
            username='admin', email='a@example.com', password='pw',
        )
        self.client_obj.force_login(u)
        _bypass_2fa(self.client_obj)
        url = reverse('crm:pipeline')
        resp = self.client_obj.get(url)
        if resp.status_code != 200:
            resp = self.client_obj.get(url, follow=True)
        self.assertEqual(resp.status_code, 200)


@override_settings(REQUIRE_2FA=False, SECURE_SSL_REDIRECT=False)
class LeadConversionTests(TestCase):
    def test_convert_creates_org_and_opportunity(self):
        from core.models import Organization
        from crm.models import Lead, Opportunity

        msp = Organization.objects.create(name='MSP4', slug='msp4')
        u = User.objects.create_superuser(
            username='su', email='su@example.com', password='pw',
        )

        lead = Lead.objects.create(
            organization=msp,
            company_name='ConvertCo',
            contact_first_name='Pat',
            contact_last_name='Kim',
            contact_email='pat@convertco.test',
            estimated_value=Decimal('5000'),
        )

        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        # Place the user inside the MSP org via session
        session = c.session
        session['current_organization_id'] = msp.id
        session['2fa_prompted'] = True
        session.save()

        url = reverse('crm:lead_convert', kwargs={'pk': lead.pk})
        resp = c.post(url, follow=False)
        # Expect a redirect to the new opportunity. Some envs may issue an
        # extra 302 first (e.g. SSL), so just check that it eventually wrote
        # the conversion.
        self.assertIn(resp.status_code, (302, 200))

        lead.refresh_from_db()
        self.assertEqual(lead.status, 'converted')
        self.assertIsNotNone(lead.converted_to_org_id)
        self.assertIsNotNone(lead.converted_to_opportunity_id)

        # Verify the new org + opportunity got built
        new_org = Organization.objects.get(pk=lead.converted_to_org_id)
        self.assertEqual(new_org.name, 'ConvertCo')
        opp = Opportunity.objects.get(pk=lead.converted_to_opportunity_id)
        self.assertEqual(opp.organization_id, msp.id)
        self.assertEqual(opp.client_org_id, new_org.id)
        self.assertEqual(opp.estimated_value, Decimal('5000'))
        self.assertEqual(opp.source_lead_id, lead.id)


@override_settings(REQUIRE_2FA=False, SECURE_SSL_REDIRECT=False)
class CRMPermissionTests(TestCase):
    def test_anonymous_blocked_from_pipeline(self):
        c = Client()
        url = reverse('crm:pipeline')
        resp = c.get(url)
        self.assertIn(resp.status_code, (302, 301, 403))

    def test_owner_passes(self):
        u = User.objects.create_superuser(
            username='owner', email='o@example.com', password='pw',
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        resp = c.get(reverse('crm:pipeline'))
        if resp.status_code != 200:
            resp = c.get(reverse('crm:pipeline'), follow=True)
        self.assertEqual(resp.status_code, 200)

    def test_basic_user_blocked_from_pipeline(self):
        """A user without any role_template should be denied (403)."""
        u = User.objects.create_user(
            username='nobody', email='n@example.com', password='pw',
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        resp = c.get(reverse('crm:pipeline'))
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# Phase 5.2 — Commission rules / engine + Lead scoring + Sales funnel
# ---------------------------------------------------------------------------


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CommissionRuleTests(TestCase):
    def _make_opp(self, *, msp_org=None, value=Decimal('1000'), assignee=None):
        from core.models import Organization
        from crm.models import Opportunity
        msp = msp_org or Organization.objects.create(name='RuleMSP', slug='rulemsp')
        client = Organization.objects.create(name='RC', slug='rc-' + str(value))
        return Opportunity.objects.create(
            organization=msp, client_org=client, name='Deal',
            estimated_value=value, assigned_to=assignee,
        )

    def test_rule_matches_value_floor(self):
        """min_value=10000 — opp with estimated_value=5000 doesn't match."""
        from crm.models import CommissionRule
        opp = self._make_opp(value=Decimal('5000'))
        rule = CommissionRule(
            organization=opp.organization, name='Big deals only',
            min_value=Decimal('10000'), rate_pct=Decimal('5'),
        )
        self.assertFalse(rule.matches(opp))

    def test_rule_matches_when_above_floor(self):
        from crm.models import CommissionRule
        opp = self._make_opp(value=Decimal('15000'))
        rule = CommissionRule(
            organization=opp.organization, name='Big deals only',
            min_value=Decimal('10000'), rate_pct=Decimal('5'),
        )
        self.assertTrue(rule.matches(opp))

    def test_inactive_rule_never_matches(self):
        from crm.models import CommissionRule
        opp = self._make_opp(value=Decimal('20000'))
        rule = CommissionRule(
            organization=opp.organization, name='Inactive',
            is_active=False, rate_pct=Decimal('10'),
        )
        self.assertFalse(rule.matches(opp))

    def test_rule_compute_pct_plus_flat(self):
        """rate_pct=10, flat=500 on a 10000 opp → 1500."""
        from crm.models import CommissionRule
        opp = self._make_opp(value=Decimal('10000'))
        rule = CommissionRule(
            organization=opp.organization, name='10% + 500',
            rate_pct=Decimal('10'), flat_amount=Decimal('500'),
        )
        self.assertEqual(rule.compute(opp), Decimal('1500'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CommissionEngineTests(TestCase):
    def test_engine_creates_commission_on_won(self):
        """Closed-won opp w/ assigned tech and matching rule → Commission created."""
        from core.models import Organization
        from crm.models import CommissionRule, Commission, Opportunity
        from crm.services import compute_commission_for_opportunity
        msp = Organization.objects.create(name='EngMSP', slug='engmsp')
        client = Organization.objects.create(name='EngCl', slug='engcl')
        tech = User.objects.create_user(username='tech1', password='pw')
        rule = CommissionRule.objects.create(
            organization=msp, name='Standard 10%',
            rate_pct=Decimal('10'), priority=50,
        )
        opp = Opportunity.objects.create(
            organization=msp, client_org=client, name='Closed deal',
            estimated_value=Decimal('5000'), stage='closed_won',
            assigned_to=tech,
        )
        commission = compute_commission_for_opportunity(opp)
        self.assertIsNotNone(commission)
        self.assertEqual(commission.amount, Decimal('500'))
        self.assertEqual(commission.user_id, tech.id)
        self.assertEqual(commission.rule_id, rule.id)
        self.assertEqual(commission.status, 'pending')
        self.assertEqual(Commission.objects.filter(opportunity=opp).count(), 1)

    def test_engine_idempotent_on_re_close(self):
        """Re-running on an already-won opp → updates, doesn't duplicate."""
        from core.models import Organization
        from crm.models import CommissionRule, Commission, Opportunity
        from crm.services import compute_commission_for_opportunity
        msp = Organization.objects.create(name='IdMSP', slug='idmsp')
        client = Organization.objects.create(name='IdCl', slug='idcl')
        tech = User.objects.create_user(username='itech', password='pw')
        CommissionRule.objects.create(
            organization=msp, name='Std', rate_pct=Decimal('10'),
        )
        opp = Opportunity.objects.create(
            organization=msp, client_org=client, name='Deal',
            estimated_value=Decimal('1000'), stage='closed_won',
            assigned_to=tech,
        )
        c1 = compute_commission_for_opportunity(opp)
        c2 = compute_commission_for_opportunity(opp)
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(Commission.objects.filter(opportunity=opp).count(), 1)

    def test_engine_no_assignee_returns_none(self):
        from core.models import Organization
        from crm.models import CommissionRule, Opportunity
        from crm.services import compute_commission_for_opportunity
        msp = Organization.objects.create(name='NoAsM', slug='noasm')
        client = Organization.objects.create(name='NoAsC', slug='noasc')
        CommissionRule.objects.create(
            organization=msp, name='Std', rate_pct=Decimal('10'),
        )
        opp = Opportunity.objects.create(
            organization=msp, client_org=client, name='No-owner deal',
            estimated_value=Decimal('1000'), stage='closed_won',
        )
        self.assertIsNone(compute_commission_for_opportunity(opp))

    def test_engine_picks_highest_priority(self):
        """Lower priority value wins."""
        from core.models import Organization
        from crm.models import CommissionRule, Opportunity
        from crm.services import compute_commission_for_opportunity
        msp = Organization.objects.create(name='PrioM', slug='priom')
        client = Organization.objects.create(name='PrioC', slug='prioc')
        tech = User.objects.create_user(username='ptech', password='pw')
        # Generic 5% (lower priority = larger number = lower precedence)
        CommissionRule.objects.create(
            organization=msp, name='Generic', rate_pct=Decimal('5'),
            priority=200,
        )
        # Premium 15% — higher precedence (priority=10)
        CommissionRule.objects.create(
            organization=msp, name='Premium', rate_pct=Decimal('15'),
            priority=10,
        )
        opp = Opportunity.objects.create(
            organization=msp, client_org=client, name='X',
            estimated_value=Decimal('1000'), stage='closed_won',
            assigned_to=tech,
        )
        commission = compute_commission_for_opportunity(opp)
        self.assertEqual(commission.amount, Decimal('150'))  # 15% of 1000


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LeadScoringTests(TestCase):
    def test_high_value_lead_scores_higher(self):
        """estimated_value=10000+ adds 20."""
        from core.models import Organization
        from crm.models import Lead
        from crm.services import score_lead
        org = Organization.objects.create(name='LSMSP', slug='lsmsp')
        low = Lead(
            organization=org, company_name='LowVal',
            estimated_value=Decimal('500'), status='contacted',
        )
        hi = Lead(
            organization=org, company_name='HighVal',
            estimated_value=Decimal('15000'), status='contacted',
        )
        self.assertGreater(score_lead(hi), score_lead(low))
        # Specifically the +20 bonus for >=10000
        self.assertEqual(score_lead(hi) - score_lead(low), 20)

    def test_score_capped_at_100(self):
        """All bonuses → still <= 100."""
        from core.models import Organization
        from crm.models import Campaign, Lead
        from crm.services import score_lead
        org = Organization.objects.create(name='CapM', slug='capm')
        camp = Campaign.objects.create(organization=org, name='C')
        owner = User.objects.create_user(username='owner1', password='pw')
        lead = Lead(
            organization=org, company_name='HotLead',
            contact_email='e@e.test', contact_phone='555',
            website='https://x.test', industry='Legal',
            employee_count=200, estimated_value=Decimal('50000'),
            status='qualified', campaign=camp, assigned_to=owner,
        )
        self.assertLessEqual(score_lead(lead), 100)

    def test_score_save_hook_populates_score(self):
        """Lead.save() auto-computes score."""
        from core.models import Organization
        from crm.models import Lead
        org = Organization.objects.create(name='SaveM', slug='savem')
        lead = Lead.objects.create(
            organization=org, company_name='S',
            contact_email='e@e.test', contact_phone='555',
            website='https://w.test', status='contacted',
        )
        # contacted (10) + email+phone (20) + website (10) = 40
        self.assertEqual(lead.score, 40)

    def test_new_status_zero_baseline(self):
        from core.models import Organization
        from crm.models import Lead
        from crm.services import score_lead
        org = Organization.objects.create(name='NewM', slug='newm')
        lead = Lead(organization=org, company_name='Bare', status='new')
        self.assertEqual(score_lead(lead), 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SalesFunnelQueryTests(TestCase):
    def test_funnel_basic(self):
        """5 leads, 2 qualified, 1 opp, 0 won → conversion rates correct."""
        from datetime import date, timedelta
        from core.models import Organization
        from crm.models import Lead, Opportunity
        from reports.queries import sales_funnel
        org = Organization.objects.create(name='FunnelM', slug='funnelm')
        client = Organization.objects.create(name='FunnelC', slug='funnelc')
        # 5 leads
        for i in range(5):
            Lead.objects.create(
                organization=org, company_name=f'Co{i}', status='new',
            )
        # 2 of them flipped to qualified
        Lead.objects.filter(company_name__in=['Co0', 'Co1']).update(status='qualified')
        # 1 opportunity in discovery
        Opportunity.objects.create(
            organization=org, client_org=client, name='OpenDeal',
            estimated_value=Decimal('1000'), stage='discovery',
        )
        today = date.today()
        f = sales_funnel(today - timedelta(days=30), today)
        self.assertEqual(f['stages'][0]['count'], 5)   # Leads
        self.assertEqual(f['stages'][1]['count'], 2)   # Qualified
        self.assertEqual(f['stages'][2]['count'], 1)   # Opportunities
        self.assertEqual(f['stages'][4]['count'], 0)   # Closed Won
        self.assertEqual(f['conversion_rates']['lead_to_qualified'], 40.0)
        self.assertEqual(f['conversion_rates']['lead_to_won'], 0.0)
        self.assertEqual(f['total_won_value'], 0.0)

    def test_funnel_with_won_value(self):
        from datetime import date, timedelta
        from core.models import Organization
        from crm.models import Opportunity
        from reports.queries import sales_funnel
        org = Organization.objects.create(name='WonM', slug='wonm')
        client = Organization.objects.create(name='WonC', slug='wonc')
        Opportunity.objects.create(
            organization=org, client_org=client, name='WonDeal',
            estimated_value=Decimal('2500'), stage='closed_won',
        )
        today = date.today()
        f = sales_funnel(today - timedelta(days=30), today)
        self.assertEqual(f['total_won_value'], 2500.0)
        self.assertEqual(f['stages'][4]['count'], 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CRMPermissionExtendedTests(TestCase):
    def test_commission_list_blocked_for_non_manager(self):
        u = User.objects.create_user(
            username='basic', email='b@example.com', password='pw',
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        resp = c.get(reverse('crm:commission_list'))
        # 403 (no permission) is the expected response for a basic user.
        self.assertEqual(resp.status_code, 403)

    def test_commission_list_allowed_for_superuser(self):
        u = User.objects.create_superuser(
            username='cmsu', email='cm@example.com', password='pw',
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        resp = c.get(reverse('crm:commission_list'))
        if resp.status_code != 200:
            resp = c.get(reverse('crm:commission_list'), follow=True)
        self.assertEqual(resp.status_code, 200)

    def test_commission_rule_list_requires_view_forecast(self):
        u = User.objects.create_user(
            username='ruser', email='r@example.com', password='pw',
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        resp = c.get(reverse('crm:commission_rule_list'))
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# Phase 5.3 — SalesActivity model + activity timeline + lead capture
# ---------------------------------------------------------------------------


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SalesActivityModelTests(TestCase):
    def test_clean_requires_one_target(self):
        from django.core.exceptions import ValidationError
        from core.models import Organization
        from crm.models import Lead, Opportunity, SalesActivity
        msp = Organization.objects.create(name='SAM', slug='sam')
        client_o = Organization.objects.create(name='SAC', slug='sac')
        lead = Lead.objects.create(organization=msp, company_name='LeadCo')
        opp = Opportunity.objects.create(
            organization=msp, client_org=client_o, name='Deal',
        )

        # No target → ValidationError
        a = SalesActivity(organization=msp, subject='No target')
        with self.assertRaises(ValidationError):
            a.clean()

        # Two targets → ValidationError
        a2 = SalesActivity(
            organization=msp, lead=lead, opportunity=opp, subject='Two',
        )
        with self.assertRaises(ValidationError):
            a2.clean()

        # Exactly one → ok
        a3 = SalesActivity(organization=msp, lead=lead, subject='Just lead')
        a3.clean()  # should not raise


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ActivityTimelineViewTests(TestCase):
    def test_lead_detail_renders_activities(self):
        from core.models import Organization
        from crm.models import Lead, SalesActivity
        msp = Organization.objects.create(name='ATM', slug='atm')
        u = User.objects.create_superuser(
            username='atu', email='atu@x.com', password='pw',
        )
        lead = Lead.objects.create(organization=msp, company_name='TimelineCo')
        SalesActivity.objects.create(
            organization=msp, lead=lead,
            activity_type='call', subject='Initial outreach',
            body='Made a cold call.', outcome='Pitched solution',
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        r = c.get(reverse('crm:lead_detail', kwargs={'pk': lead.pk}))
        if r.status_code != 200:
            r = c.get(reverse('crm:lead_detail', kwargs={'pk': lead.pk}), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Activity timeline', r.content)
        self.assertIn(b'Initial outreach', r.content)

    def test_activity_add_creates_row(self):
        from core.models import Organization
        from crm.models import Lead, SalesActivity
        msp = Organization.objects.create(name='AAM', slug='aam')
        u = User.objects.create_superuser(
            username='aau', email='aau@x.com', password='pw',
        )
        lead = Lead.objects.create(organization=msp, company_name='AddCo')
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        url = reverse('crm:activity_add', kwargs={'scope': 'lead', 'pk': lead.pk})
        r = c.post(url, {
            'activity_type': 'meeting',
            'subject': 'Discovery call',
            'body': 'Discussed needs.',
            'outcome': 'Move to qualified',
            'duration_minutes': '45',
        })
        self.assertIn(r.status_code, (302, 200))
        self.assertEqual(SalesActivity.objects.filter(lead=lead).count(), 1)
        a = SalesActivity.objects.get(lead=lead)
        self.assertEqual(a.subject, 'Discovery call')
        self.assertEqual(a.duration_minutes, 45)
        self.assertEqual(a.source, 'manual')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WebFormLeadCaptureTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        from core.models import Organization
        # Need an active MSP org to receive the lead
        self.msp = Organization.objects.create(
            name='WebCaptureMSP', slug='webcapturemsp',
        )

    def test_creates_lead_and_activity(self):
        from crm.models import Lead, SalesActivity
        c = Client()
        url = reverse('crm:lead_capture_web')
        r = c.post(url, {
            'company_name': 'NewProspect Inc',
            'email': 'prospect@example.com',
            'first_name': 'Pat',
            'last_name': 'Doe',
            'phone': '555-1212',
            'notes': 'Need help with backups.',
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get('success'))
        lead = Lead.objects.get(pk=body['lead_id'])
        self.assertEqual(lead.company_name, 'NewProspect Inc')
        self.assertEqual(lead.contact_email, 'prospect@example.com')
        self.assertEqual(lead.source, 'web_form')
        self.assertEqual(lead.status, 'new')
        # Auto SalesActivity attached
        acts = SalesActivity.objects.filter(lead=lead)
        self.assertEqual(acts.count(), 1)
        self.assertEqual(acts.first().activity_type, 'inbound')
        self.assertEqual(acts.first().source, 'web_form')

    def test_honeypot_rejects_silently(self):
        from crm.models import Lead
        c = Client()
        url = reverse('crm:lead_capture_web')
        r = c.post(url, {
            'company_name': 'BotCo',
            'email': 'bot@example.com',
            'website_url': 'http://spam.test',  # honeypot triggered
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get('success'))  # silently accepted
        self.assertFalse(Lead.objects.filter(company_name='BotCo').exists())

    def test_missing_required_returns_400(self):
        c = Client()
        url = reverse('crm:lead_capture_web')
        r = c.post(url, {'company_name': 'OnlyCompany'})  # email missing
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())

    def test_rate_limit_returns_429(self):
        from django.core.cache import cache
        cache.clear()
        c = Client()
        url = reverse('crm:lead_capture_web')
        # 10 successful submissions
        for i in range(10):
            r = c.post(url, {
                'company_name': f'Co{i}',
                'email': f'c{i}@example.com',
            })
            self.assertEqual(r.status_code, 200)
        # 11th should be rate-limited
        r = c.post(url, {
            'company_name': 'OverflowCo',
            'email': 'overflow@example.com',
        })
        self.assertEqual(r.status_code, 429)


# ---------------------------------------------------------------------------
# v3.17.154 — CRM feature toggle (SystemSetting.crm_enabled)
# ---------------------------------------------------------------------------


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FeatureToggleTests(TestCase):
    """Verify the CRM dropdown is hidden when crm_enabled=False."""

    def test_crm_dropdown_hidden_when_disabled(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.crm_enabled = False
        s.save()
        u = User.objects.create_user(
            'crmtoggle_user', 'ct@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        # Hit the dashboard which extends base.html. follow=True to chase
        # any org-context redirects to a final 200 page that still has
        # base.html's nav rendered.
        r = c.get('/core/dashboard/', follow=True)
        self.assertEqual(r.status_code, 200)
        # v3.17.580 — CRM is a section of the More menu rather than its own
        # top-level dropdown, so the check is on the destination rather than
        # on a container id that no longer exists.
        self.assertNotIn(b'/crm/pipeline/', r.content)

    def test_crm_dropdown_shown_when_enabled(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.crm_enabled = True
        s.save()
        u = User.objects.create_user(
            'crmtoggle_user2', 'ct2@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        _bypass_2fa(c)
        r = c.get('/core/dashboard/', follow=True)
        self.assertEqual(r.status_code, 200)
        # v3.17.580 — see the note in the sibling test: CRM lives under More.
        self.assertIn(b'/crm/pipeline/', r.content)
        self.assertIn(b'moreNavDropdown', r.content)
