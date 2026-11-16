from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, RoleTemplate, UserProfile, UserType
from audit.models import AuditLog
from contracts.models import ContractDocument
from core.models import Organization

from . import access, engine, registry
from .models import OnboardingSession as S, OnboardingStepState as St
from .registry import StepError

User = get_user_model()

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

FLAGS = dict(
    manage_customer_onboarding=True, org_manage_settings=True, assets_create=True, crm_manage_pipeline=True,
    integrations_configure=True, contracts_view=True, contracts_view_pricing=True, contracts_edit_draft=True,
    contracts_submit_approval=True, contracts_send=True, contracts_approve=True)


def make_staff(username, scope=None, **overrides):
    """An MSP technician whose global role holds the wizard permission and the
    permissions of the things the steps change (override to remove some)."""
    flags = dict(FLAGS)
    flags.update(overrides)
    user = User.objects.create_user(username, f'{username}@example.com', 'pw')
    role = RoleTemplate.objects.create(name=f'{username} role', **flags)
    profile = user.profile
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    if scope is not None:
        profile.client_scope = 'selected'
    profile.save()
    if scope is not None:
        profile.scope_organizations.set(scope)
    user.refresh_from_db()
    return user


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('psa_seed_defaults', verbosity=0)
        cls.tenant = Organization.objects.create(name='MSP Home', slug='msp-home',
                                                 organization_type=Organization.TYPE_INTERNAL)
        cls.other_tenant = Organization.objects.create(name='Other MSP', slug='other-msp')
        cls.tech = make_staff('tech')

    def new_session(self, user=None, kind=S.NEW_CUSTOMER, client=None):
        return engine.create_session(user or self.tech, kind, self.tenant, client)

    def apply(self, session, key, data=None, user=None):
        form, summary = engine.apply_step(session, key, data or {}, user or self.tech)
        if summary is None:
            self.fail(f'{key} did not apply: {form.errors.as_json() if form else ""}')
        session.refresh_from_db()
        return summary

    def customer(self, session, name='Acme Dental', **extra):
        data = {'mode': 'new', 'name': name}
        data.update(extra)
        return self.apply(session, 'customer', data)


class EngineTests(Base):
    def test_new_customer_has_nineteen_steps_in_order(self):
        keys = [s.key for s in registry.steps_for(S.NEW_CUSTOMER)]
        self.assertEqual(len(keys), 19)
        self.assertEqual(keys[0], 'customer')
        self.assertEqual(keys[-1], 'activate')
        self.assertLess(keys.index('send_approval'), keys.index('activate'))

    def test_session_starts_with_a_state_per_step(self):
        s = self.new_session()
        self.assertEqual(s.step_states.count(), 19)
        self.assertEqual(s.current_step, 'customer')
        self.assertEqual(s.status, S.DRAFT)
        self.assertTrue(all(st.status == St.NOT_STARTED for st in s.step_states.all()))

    def test_customer_step_creates_customer_and_nothing_else_is_required(self):
        s = self.new_session()
        summary = self.customer(s)
        self.assertIn('Created customer', summary)
        self.assertEqual(s.status, S.IN_PROGRESS)
        client = s.client
        self.assertEqual(client.name, 'Acme Dental')
        self.assertFalse(client.is_active, 'kept inactive until activation by default')
        self.assertTrue(Membership.objects.filter(user=self.tech, organization=client, role='owner').exists())
        self.assertEqual(s.current_step, 'locations')
        # partial completion: the session is open and the customer exists with no other step done
        self.assertEqual(s.step_states.filter(status=St.DONE).count(), 1)
        self.assertTrue(s.is_open)

    def test_customer_can_be_active_immediately(self):
        s = self.new_session()
        self.customer(s, hide_until_activation='')
        self.assertTrue(s.client.is_active)

    def test_duplicate_customer_name_is_a_form_error(self):
        Organization.objects.create(name='Acme Dental', slug='acme-dental')
        s = self.new_session()
        form, summary = engine.apply_step(s, 'customer', {'mode': 'new', 'name': 'acme dental'}, self.tech)
        self.assertIsNone(summary)
        self.assertIn('name', form.errors)
        self.assertIsNone(S.objects.get(pk=s.pk).client)

    def test_use_existing_customer(self):
        existing = Organization.objects.create(name='Existing Co', slug='existing-co')
        s = self.new_session()
        self.apply(s, 'customer', {'mode': 'existing', 'existing': existing.pk})
        self.assertEqual(s.client, existing)

    def test_steps_need_a_customer_first(self):
        s = self.new_session()
        with self.assertRaises(StepError):
            engine.apply_step(s, 'locations', {}, self.tech)

    def test_resume_returns_to_the_next_open_step(self):
        s = self.new_session()
        self.customer(s)
        engine.skip_step(s, 'locations', self.tech)
        again = S.objects.get(pk=s.pk)  # "later": a fresh load
        self.assertEqual(again.current_step, 'service_plan')
        rows = engine.progress(again)
        self.assertEqual([r['status'] for r in rows[:2]], [St.DONE, St.SKIPPED])
        counts = engine.counts(again)
        self.assertEqual((counts['done'], counts['skipped']), (1, 1))

    def test_reapplying_customer_step_updates_instead_of_duplicating(self):
        s = self.new_session()
        self.customer(s)
        engine.reopen_step(s, 'customer', self.tech)
        self.apply(s, 'customer', {'name': 'Acme Dental Group', 'city': 'Austin'})
        self.assertEqual(Organization.objects.filter(name__startswith='Acme Dental').count(), 1)
        s.client.refresh_from_db()
        self.assertEqual((s.client.name, s.client.city), ('Acme Dental Group', 'Austin'))

    def test_skip_rules(self):
        s = self.new_session()
        with self.assertRaises(StepError):
            engine.skip_step(s, 'customer', self.tech)  # the first step is required
        engine.skip_step(s, 'quantities', self.tech, note='later')
        st = s.step_states.get(step_key='quantities')
        self.assertEqual((st.status, st.notes), (St.SKIPPED, 'later'))
        # unavailable steps are skippable even if they would not be otherwise
        engine.skip_step(s, 'service_plan', self.tech)

    def test_cancelled_session_is_closed(self):
        s = self.new_session()
        engine.cancel_session(s, self.tech)
        self.assertEqual(s.status, S.CANCELLED)
        with self.assertRaises(StepError):
            engine.apply_step(s, 'customer', {'mode': 'new', 'name': 'X'}, self.tech)

    def test_every_applied_step_is_audited(self):
        s = self.new_session()
        self.customer(s)
        self.apply(s, 'quantities', {'users': 10})
        logs = AuditLog.objects.filter(object_type='OnboardingSession', object_id=s.pk)
        self.assertGreaterEqual(logs.count(), 3)  # started + two steps
        step_logs = logs.filter(extra_data__step__in=['customer', 'quantities'])
        self.assertEqual(step_logs.count(), 2)
        self.assertTrue(all(l.user == self.tech for l in step_logs))
        self.assertEqual(step_logs.get(extra_data__step='customer').organization, s.client)


def without(*labels):
    """Simulate apps that are not installed."""
    real = apps_is_installed

    def fake(label):
        return False if label in labels else real(label)
    return mock.patch('django.apps.apps.is_installed', side_effect=fake)


from django.apps import apps as _apps  # noqa: E402
apps_is_installed = _apps.is_installed


class AvailabilityTests(Base):
    def test_pricing_steps_unavailable_without_the_app(self):
        with without('pricing'):
            for key in ('service_plan', 'add_ons', 'customer_pricing'):
                step = registry.get_step(key)
                self.assertFalse(step.is_available(), key)
                self.assertIn('Available once the price book is enabled', step.unavailable_reason())

    def test_pricing_steps_available_with_the_app(self):
        for key in ('service_plan', 'add_ons', 'customer_pricing'):
            self.assertTrue(registry.get_step(key).is_available(), key)
        # installed app whose model cannot be resolved: still unavailable
        with mock.patch('onboarding.steps.pricing.plan_model', return_value=None):
            self.assertFalse(registry.get_step('service_plan').is_available())

    def test_backup_step_unavailable_without_the_app(self):
        with without('backup_monitoring'):
            step = registry.get_step('backup_monitoring')
            self.assertFalse(step.is_available())
            self.assertIn('backup monitoring', step.unavailable_reason())

    def test_applying_an_unavailable_step_is_refused_not_faked(self):
        s = self.new_session()
        self.customer(s)
        with without('pricing'):
            with self.assertRaises(StepError) as cm:
                engine.apply_step(s, 'service_plan', {}, self.tech)
        self.assertIn('Available once', str(cm.exception))
        self.assertFalse(s.step_states.filter(step_key='service_plan', status=St.DONE).exists())

    def _plan(self, **kw):
        from pricing.models import ServicePlan
        return ServicePlan.objects.create(organization=None, **kw)

    def test_service_plan_uses_real_plan_prices_and_records_missing_ones(self):
        from onboarding.steps import common
        plan = self._plan(name='Gold', monthly_price=Decimal('500.00'), per_user_price=Decimal('40.00'),
                          per_device_price=Decimal('20.00'))
        s = self.new_session()
        self.customer(s)
        self.apply(s, 'quantities', {'users': 10})  # no devices recorded
        self.apply(s, 'service_plan', {'plan': plan.pk})
        rows = s.step_data('service_plan')['lines']
        by = {r['name']: r for r in rows}
        self.assertEqual(by['Gold']['unit_price'], '500.00')
        self.assertEqual((by['Gold: per user']['quantity'], by['Gold: per user']['unit_price']), ('10', '40.00'))
        self.assertIsNone(by['Gold: per device']['unit_price'])   # missing, not zero
        self.assertIn('no number of devices', by['Gold: per device']['reason'])
        lines = common.lines_from_session(s)
        self.assertEqual([l['description'] for l in lines], ['Gold', 'Gold: per user'])
        self.assertTrue(any('per device' in m for m in common.missing_prices(s)))

    def test_plan_without_any_price_is_missing_never_zero(self):
        from onboarding.steps import common
        plan = self._plan(name='Unpriced')
        s = self.new_session()
        self.customer(s)
        self.apply(s, 'service_plan', {'plan': plan.pk})
        self.assertEqual(common.lines_from_session(s), [])
        self.assertTrue(common.missing_prices(s))

    def test_generate_refuses_missing_prices_unless_left_out(self):
        plan = self._plan(name='Half', monthly_price=Decimal('100'), per_user_price=Decimal('5'))
        s = self.new_session()
        self.customer(s)
        self.apply(s, 'service_plan', {'plan': plan.pk})
        form, summary = engine.apply_step(s, 'generate_document', {'document': 'agreement'}, self.tech)
        self.assertIsNone(summary)
        self.assertIn('no price', str(form.non_field_errors()).lower())
        self.apply(s, 'generate_document', {'document': 'agreement', 'leave_out_unpriced': 'on'})
        self.assertEqual([l['description'] for l in s.agreement.line_items], ['Half'])

    def test_plans_are_install_wide_or_the_customers_own(self):
        other = Organization.objects.create(name='Other Cust', slug='other-cust')
        mine = self._plan(name='Everyone', monthly_price=Decimal('1'))
        from pricing.models import ServicePlan
        theirs = ServicePlan.objects.create(organization=other, name='Theirs', monthly_price=Decimal('1'))
        s = self.new_session()
        self.customer(s)
        offered = set(registry.get_step('service_plan').plans(s, False))
        self.assertIn(mine, offered)
        self.assertNotIn(theirs, offered)

    def test_customer_pricing_flags_discounts_that_need_approval(self):
        s = self.new_session()
        self.customer(s)
        self.apply(s, 'customer_pricing', {'discount_percent': '10'})
        self.assertTrue(s.step_data('customer_pricing')['needs_discount_approval'])

    def test_no_cost_data_enters_the_session(self):
        plan = self._plan(name='Gold', monthly_price=Decimal('500.00'))
        s = self.new_session()
        self.customer(s)
        self.apply(s, 'service_plan', {'plan': plan.pk})
        blob = str(s.data).lower()
        self.assertNotIn('cost', blob)
        self.assertNotIn('margin', blob)

    def test_payment_method_field_only_with_payments(self):
        from onboarding.steps.core import PaymentForm
        with mock.patch('django.apps.apps.is_installed', return_value=False):
            self.assertNotIn('method', PaymentForm().fields)
        with mock.patch('django.apps.apps.is_installed', return_value=True):
            self.assertIn('method', PaymentForm().fields)

    def test_contributed_step_registers_into_a_kind(self):
        class Extra(registry.Step):
            key = 'zz_extra'
            title = 'Extra'
            needs_client = False

            def apply(self, session, cleaned, user, request=None):
                return 'extra done'
        try:
            registry.register_step(Extra, kinds=(S.NEW_CUSTOMER,), after='warranty')
            keys = [s.key for s in registry.steps_for(S.NEW_CUSTOMER)]
            self.assertEqual(keys[keys.index('warranty') + 1], 'zz_extra')
            s = self.new_session()
            self.assertEqual(s.step_states.count(), 20)
            self.customer(s)
            self.apply(s, 'zz_extra')
        finally:
            registry._STEPS.pop('zz_extra', None)
            registry._KINDS[S.NEW_CUSTOMER].remove('zz_extra')


class CoreStepTests(Base):
    def setUp(self):
        self.s = self.new_session()
        self.customer(self.s)
        self.client_org = self.s.client

    def test_locations(self):
        from locations.models import Location
        data = {'name': 'HQ', 'location_type': 'office', 'street_address': '1 Main St', 'city': 'Austin',
                'state': 'TX', 'postal_code': '78701', 'country': 'United States', 'is_primary': 'on'}
        self.apply(self.s, 'locations', data)
        self.apply(self.s, 'locations', dict(data, name='Branch', is_primary=''))
        locs = Location.objects.filter(organization=self.client_org)
        self.assertEqual(locs.count(), 2)
        self.assertEqual(locs.filter(is_primary=True).get().name, 'HQ')
        self.assertEqual(len(self.s.step_data('locations')['location_ids']), 2)

    def test_locations_need_asset_create_permission(self):
        weak = make_staff('weak', assets_create=False)
        s = self.new_session(weak)
        engine.apply_step(s, 'customer', {'mode': 'new', 'name': 'Weak Co'}, weak)
        with self.assertRaises(StepError) as cm:
            engine.apply_step(s, 'locations', {'name': 'x'}, weak)
        self.assertIn('assets_create', str(cm.exception))

    def test_quantities_feed_draft_lines(self):
        self.apply(self.s, 'quantities', {'users': 12, 'devices': 15, 'price_users': '85.00',
                                          'price_devices': '25.50'})
        from onboarding.steps import common
        lines = common.lines_from_session(self.s)
        self.assertEqual([(l['quantity'], l['unit_price']) for l in lines], [('12', '85.00'), ('15', '25.50')])
        self.assertTrue(all(l['kind'] == 'recurring' for l in lines))

    def test_contract_template_creates_a_draft_agreement(self):
        self.apply(self.s, 'contract_template', {'title': 'MSA'})
        ag = self.s.agreement
        self.assertEqual((ag.status, ag.title, ag.organization), (ContractDocument.DRAFT, 'MSA', self.client_org))
        # running it again keeps the same draft
        self.apply(self.s, 'contract_template', {'title': 'Other'})
        self.assertEqual(ContractDocument.objects.filter(organization=self.client_org).count(), 1)

    def test_contract_template_needs_contract_permission(self):
        weak = make_staff('nocontract', contracts_edit_draft=False)
        s = self.new_session(weak)
        engine.apply_step(s, 'customer', {'mode': 'new', 'name': 'NC Co'}, weak)
        with self.assertRaises(StepError):
            engine.apply_step(s, 'contract_template', {}, weak)
        self.assertFalse(ContractDocument.objects.filter(organization=s.client).exists())

    def test_sla(self):
        from psa.models import TicketPriority
        code = TicketPriority.objects.first().code
        self.apply(self.s, 'sla', {f'response_{code}': 30, f'resolution_{code}': 240})
        self.client_org.refresh_from_db()
        self.assertEqual(self.client_org.sla_overrides, {code: {'response_minutes': 30, 'resolution_minutes': 240}})

    def test_account_manager_billing_and_terms_land_on_the_draft(self):
        mgr = User.objects.create_user('mgr', 'mgr@example.com', 'pw', first_name='Mia')
        mgr.profile.user_type = UserType.STAFF
        mgr.profile.save()
        self.apply(self.s, 'account_manager', {'user': mgr.pk})  # no draft yet: recorded
        self.apply(self.s, 'billing_frequency', {'frequency': 'quarterly'})
        self.apply(self.s, 'payment', {'terms': 'Net 45'})
        self.apply(self.s, 'contract_template', {'title': 'MSA'})  # applied when the draft appears
        ag = self.s.agreement
        ag.refresh_from_db()
        self.assertEqual((ag.account_manager, ag.billing_frequency, ag.payment_terms), (mgr, 'quarterly', 'Net 45'))
        self.apply(self.s, 'billing_frequency', {'frequency': 'annually'})
        ag.refresh_from_db()
        self.assertEqual(ag.billing_frequency, 'annually')

    def _accounting(self):
        from integrations.models import AccountingConnection
        return AccountingConnection.objects.create(provider_type='quickbooks_online', name='QBO', organization=None)

    def test_accounting_mapping_links_customer(self):
        from integrations.models import AccountingCustomerLink
        conn = self._accounting()
        self.apply(self.s, 'accounting_mapping', {'connection': conn.pk, 'provider_customer_id': '58',
                                                  'display_name': 'Acme'})
        link = AccountingCustomerLink.objects.get(client_org=self.client_org)
        self.assertEqual((link.connection, link.provider_customer_id, link.source), (conn, '58', 'matched'))

    def test_accounting_mapping_refuses_a_customer_claimed_by_another(self):
        from integrations.models import AccountingCustomerLink
        conn = self._accounting()
        rival = Organization.objects.create(name='Rival', slug='rival')
        AccountingCustomerLink.objects.create(connection=conn, client_org=rival, provider_customer_id='58')
        form, summary = engine.apply_step(self.s, 'accounting_mapping',
                                          {'connection': conn.pk, 'provider_customer_id': '58'}, self.tech)
        self.assertIsNone(summary)
        self.assertIn('already linked', str(form.non_field_errors()))
        self.assertFalse(AccountingCustomerLink.objects.filter(client_org=self.client_org).exists())

    def test_accounting_mapping_needs_integration_permission(self):
        weak = make_staff('nointeg', integrations_configure=False)
        s = self.new_session(weak)
        engine.apply_step(s, 'customer', {'mode': 'new', 'name': 'NI Co'}, weak)
        with self.assertRaises(StepError):
            engine.apply_step(s, 'accounting_mapping', {'connection': self._accounting().pk,
                                                        'provider_customer_id': '1'}, weak)

    def test_rmm_mapping(self):
        from integrations.models import ExternalObjectMap, RMMConnection
        conn = RMMConnection.objects.create(provider_type='tactical_rmm', name='Tactical', base_url='https://r.example',
                                            organization=None)
        self.apply(self.s, 'rmm', {'connection': conn.pk, 'rmm_client_id': '12', 'rmm_client_name': 'Acme'})
        row = ExternalObjectMap.objects.get(external_type='rmm_client', external_id='12')
        self.assertEqual((row.local_type, row.local_id), ('organization', self.client_org.pk))

    def test_rmm_needs_an_identifier(self):
        from integrations.models import RMMConnection
        conn = RMMConnection.objects.create(provider_type='tactical_rmm', name='Tactical', base_url='https://r.example',
                                            organization=None)
        form, summary = engine.apply_step(self.s, 'rmm', {'connection': conn.pk}, self.tech)
        self.assertIsNone(summary)

    def test_distributors_are_recorded_on_the_session_only(self):
        from integrations.models import DistributorConnection
        d = DistributorConnection.objects.create(provider_type='pax8', name='Pax8', organization=None)
        self.apply(self.s, 'distributors', {'connections': [d.pk], 'account_numbers': 'PX-1'})
        self.assertEqual(self.s.step_data('distributors')['names'], ['Pax8'])

    def test_warranty_records_decision(self):
        summary = self.apply(self.s, 'warranty', {'track': 'on'})
        self.assertIn('wanted', summary)

    def test_generate_document_makes_drafts_only(self):
        from psa.models import Contract, Quote
        self.apply(self.s, 'quantities', {'users': 10, 'price_users': '90'})
        self.apply(self.s, 'generate_document', {'document': 'both', 'valid_days': 14})
        ag, q = self.s.agreement, self.s.quote
        self.assertEqual(ag.status, ContractDocument.DRAFT)
        self.assertEqual(ag.line_items[0]['quantity'], '10')
        self.assertEqual(Decimal(ag.recurring_total), Decimal('900.00'))
        self.assertEqual((q.status, q.total), ('draft', Decimal('900.00')))
        self.assertEqual(q.client_org, self.client_org)
        self.assertFalse(Contract.objects.filter(client_org=self.client_org).exists(), 'no billing contract')

    def test_send_approval_needs_a_draft(self):
        with self.assertRaises(StepError):
            engine.apply_step(self.s, 'send_approval', {}, self.tech)

    def test_send_for_approval_uses_existing_flows(self):
        from psa.models import PSAApproval
        self.apply(self.s, 'quantities', {'users': 2, 'price_users': '50'})
        self.apply(self.s, 'generate_document', {'document': 'both'})
        self.apply(self.s, 'send_approval', {'submit_agreement': 'on', 'submit_quote': 'on'})
        ag = self.s.agreement
        ag.refresh_from_db()
        self.assertIn(ag.status, (ContractDocument.PENDING_APPROVAL, ContractDocument.READY))
        self.assertTrue(PSAApproval.objects.filter(object_type='psa.Quote', object_id=self.s.quote_id,
                                                   status='pending').exists())
        self.assertEqual(self.s.status, S.AWAITING_APPROVAL)
        self.s.quote.refresh_from_db()
        self.assertEqual(self.s.quote.status, 'draft', 'the quote is not sent or accepted from the wizard')

    def test_send_approval_needs_contract_submit_permission(self):
        weak = make_staff('nosubmit', contracts_submit_approval=False)
        s = self.new_session(weak)
        engine.apply_step(s, 'customer', {'mode': 'new', 'name': 'NS Co'}, weak)
        engine.apply_step(s, 'quantities', {'users': 1, 'price_users': '10'}, weak)
        engine.apply_step(s, 'generate_document', {'document': 'agreement'}, weak)
        form, summary = engine.apply_step(s, 'send_approval', {'submit_agreement': 'on'}, weak)
        self.assertIsNone(summary)
        s.agreement.refresh_from_db()
        self.assertEqual(s.agreement.status, ContractDocument.DRAFT)

    def test_activate_waits_for_signature_unless_overridden(self):
        self.apply(self.s, 'generate_document', {'document': 'agreement'})
        form, summary = engine.apply_step(self.s, 'activate', {}, self.tech)
        self.assertIsNone(summary)
        self.client_org.refresh_from_db()
        self.assertFalse(self.client_org.is_active)
        self.apply(self.s, 'activate', {'activate_unsigned': 'on'})
        self.client_org.refresh_from_db()
        self.assertTrue(self.client_org.is_active)
        self.assertEqual(self.s.status, S.COMPLETED)
        self.assertIsNotNone(self.s.completed_at)

    def test_activate_signed_creates_a_draft_billing_contract(self):
        from psa.models import Contract
        self.apply(self.s, 'generate_document', {'document': 'agreement'})
        ContractDocument.objects.filter(pk=self.s.agreement_id).update(status=ContractDocument.SIGNED,
                                                                       signed_at=timezone.now())
        self.apply(self.s, 'activate', {})
        bc = Contract.objects.get(client_org=self.client_org)
        self.assertEqual(bc.status, 'draft')


class LifecycleTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from contracts import services
        from psa.models import Contract
        cls.client_org = Organization.objects.create(name='Established', slug='established')
        doc = services.create_contract(cls.client_org, cls.tech, title='MSA')
        services.save_draft(doc, {'line_items': [
            {'description': 'Managed users', 'kind': 'recurring', 'quantity': '10', 'unit_price': '100.00',
             'discount_percent': '0', 'taxable': False}]}, cls.tech)
        ContractDocument.objects.filter(pk=doc.pk).update(status=ContractDocument.SIGNED, signed_at=timezone.now())
        cls.signed = ContractDocument.objects.get(pk=doc.pk)
        cls.billing = Contract.objects.create(
            organization=cls.client_org, client_org=cls.client_org, name='Managed', status='active',
            contract_type='managed_services', start_date=date(2026, 1, 1), billing_frequency='monthly',
            recurring_amount=Decimal('1000'), proration_enabled=True)

    def test_kinds_have_smaller_step_sets(self):
        for kind in S.LIFECYCLE_KINDS if hasattr(S, 'LIFECYCLE_KINDS') else [k for k, _ in S.KINDS if k != S.NEW_CUSTOMER]:
            keys = [s.key for s in registry.steps_for(kind)]
            self.assertLess(len(keys), 10, kind)
            self.assertEqual(keys[0], 'select_client')
            self.assertEqual(keys[-1], 'send_approval')

    def test_lifecycle_session_needs_a_customer_and_marks_it_done(self):
        with self.assertRaises(StepError):
            engine.create_session(self.tech, S.ADD_USERS, self.tenant, None)
        s = engine.create_session(self.tech, S.ADD_USERS, self.tenant, self.client_org)
        self.assertEqual(s.step_states.get(step_key='select_client').status, St.DONE)
        self.assertEqual(s.current_step, 'change_details')

    def _change(self, kind, details, target='auto', user=None):
        user = user or self.tech
        s = engine.create_session(user, kind, self.tenant, self.client_org)
        if kind == S.ADD_LOCATION:
            engine.skip_step(s, 'locations', user)
        for key in ('service_plan', 'add_ons', 'customer_pricing'):
            if key in [x.key for x in registry.steps_for(kind)]:
                engine.skip_step(s, key, user)
        engine.apply_step(s, 'change_details', details, user)
        return s, engine.apply_step(s, 'change_draft', {'target': target}, user)

    def test_add_users_creates_a_draft_amendment_and_changes_nothing_active(self):
        before = (self.billing.recurring_amount, self.billing.status, self.signed.line_items)
        s, (form, summary) = self._change(S.ADD_USERS, {'quantity': 5, 'unit_price': '100', 'effective_date':
                                                        '2026-11-10'})
        self.assertIsNotNone(summary, form.errors if form else '')
        s.refresh_from_db()
        amend = s.agreement
        self.assertEqual((amend.status, amend.relation, amend.related_contract), (
            ContractDocument.DRAFT, 'amends', self.signed))
        self.assertEqual([l['quantity'] for l in amend.line_items], ['10', '5'])
        self.assertTrue(any(sec['title'] == 'Change summary' for sec in amend.sections))
        # the live records did not move
        from psa.models import Contract
        self.signed.refresh_from_db()
        self.billing.refresh_from_db()
        self.assertEqual((self.billing.recurring_amount, self.billing.status, self.signed.line_items), before)
        self.assertEqual(self.signed.status, ContractDocument.SIGNED)
        self.assertEqual(Contract.objects.filter(client_org=self.client_org).count(), 1)

    def test_price_increase_scales_the_draft_not_the_signed_agreement(self):
        s, (form, summary) = self._change(S.PRICE_INCREASE, {'percent': '5', 'effective_date': '2027-01-01'})
        self.assertIsNotNone(summary, form.errors if form else '')
        s.refresh_from_db()
        self.assertEqual(s.agreement.line_items[0]['unit_price'], '105.00')
        self.signed.refresh_from_db()
        self.assertEqual(self.signed.line_items[0]['unit_price'], '100.00')

    def test_renewal_makes_a_renewal_draft(self):
        s, (form, summary) = self._change(S.RENEWAL, {'term_months': 24, 'price_adjustment_percent': '3'})
        self.assertIsNotNone(summary, form.errors if form else '')
        s.refresh_from_db()
        self.assertEqual((s.agreement.relation, s.agreement.duration_months, s.agreement.status),
                         ('renews', 24, ContractDocument.DRAFT))
        self.assertEqual(s.agreement.line_items[0]['unit_price'], '103.00')

    def test_offboarding_makes_a_draft_and_leaves_customer_active(self):
        s, (form, summary) = self._change(S.OFFBOARDING, {'end_date': '2026-12-31', 'reason': 'Moving'})
        self.assertIsNotNone(summary, form.errors if form else '')
        self.client_org.refresh_from_db()
        self.assertTrue(self.client_org.is_active)
        s.refresh_from_db()
        self.assertEqual(s.agreement.status, ContractDocument.DRAFT)

    def test_quote_target_for_quantity_changes(self):
        s, (form, summary) = self._change(S.ADD_DEVICES, {'quantity': 4, 'unit_price': '30',
                                                          'effective_date': '2026-11-10'}, target='quote')
        self.assertIsNotNone(summary, form.errors if form else '')
        s.refresh_from_db()
        self.assertEqual((s.quote.status, s.quote.total), ('draft', Decimal('120.00')))
        self.assertIsNone(s.agreement)

    def test_remove_users_quote_is_a_credit_draft(self):
        s, (form, summary) = self._change(S.REMOVE_USERS, {'quantity': 2, 'unit_price': '100',
                                                           'effective_date': '2026-11-10'}, target='quote')
        s.refresh_from_db()
        self.assertEqual(s.quote.total, Decimal('-200.00'))

    def test_renewal_without_a_signed_agreement_is_refused(self):
        lone = Organization.objects.create(name='No Paper', slug='no-paper')
        s = engine.create_session(self.tech, S.RENEWAL, self.tenant, lone)
        engine.apply_step(s, 'change_details', {'term_months': 12}, self.tech)
        form, summary = engine.apply_step(s, 'change_draft', {'target': 'auto'}, self.tech)
        self.assertIsNone(summary)
        self.assertIn('signed agreement', str(form.non_field_errors()))

    def test_no_signed_agreement_falls_back_to_a_quote(self):
        lone = Organization.objects.create(name='Fresh', slug='fresh')
        s = engine.create_session(self.tech, S.ADD_USERS, self.tenant, lone)
        engine.apply_step(s, 'change_details', {'quantity': 3, 'unit_price': '80', 'effective_date': '2026-11-10'},
                          self.tech)
        form, summary = engine.apply_step(s, 'change_draft', {'target': 'auto'}, self.tech)
        self.assertIsNotNone(summary)
        s.refresh_from_db()
        self.assertEqual(s.quote.total, Decimal('240.00'))

    def test_draft_goes_through_the_existing_approval_workflow(self):
        s, _ = self._change(S.ADD_USERS, {'quantity': 1, 'unit_price': '100', 'effective_date': '2026-11-10'})
        engine.apply_step(s, 'send_approval', {'submit_agreement': 'on'}, self.tech)
        s.refresh_from_db()
        s.agreement.refresh_from_db()
        self.assertIn(s.agreement.status, (ContractDocument.PENDING_APPROVAL, ContractDocument.READY))
        self.assertIn(s.status, (S.AWAITING_APPROVAL, S.AWAITING_SIGNATURE))
        self.assertNotEqual(s.agreement.status, ContractDocument.SIGNED)

    def test_proration_preview_uses_the_contract_helper(self):
        s = engine.create_session(self.tech, S.ADD_USERS, self.tenant, self.client_org)
        engine.apply_step(s, 'change_details', {'quantity': 10, 'unit_price': '30', 'effective_date': '2026-11-16'},
                          self.tech)
        from .steps.lifecycle import proration_preview
        prev = proration_preview(s)
        # 15 of 30 days of November remain
        self.assertEqual(prev['factor'], Decimal('0.5000'))
        self.assertEqual(prev['full'], Decimal('300.00'))
        self.assertEqual(prev['prorated'], Decimal('150.00'))
        self.assertTrue(prev['proration_on'])

    def test_proration_preview_without_a_price_says_so(self):
        s = engine.create_session(self.tech, S.ADD_USERS, self.tenant, self.client_org)
        from .steps.lifecycle import proration_preview
        self.assertIn('note', proration_preview(s))
        self.assertNotIn('factor', proration_preview(s))

    def test_add_location_flow(self):
        from locations.models import Location
        s = engine.create_session(self.tech, S.ADD_LOCATION, self.tenant, self.client_org)
        engine.apply_step(s, 'locations', {'name': 'Branch', 'location_type': 'branch', 'street_address': '2 Elm',
                                           'city': 'Dallas', 'postal_code': '75001', 'country': 'US'}, self.tech)
        self.assertTrue(Location.objects.filter(organization=self.client_org, name='Branch').exists())
        engine.apply_step(s, 'change_details', {'monthly_price': '150', 'effective_date': '2026-11-10'}, self.tech)
        form, summary = engine.apply_step(s, 'change_draft', {'target': 'agreement'}, self.tech)
        self.assertIsNotNone(summary, form.errors if form else '')


class PermissionTests(Base):
    def test_permission_is_registered_staff_only_and_off_by_default(self):
        from accounts.permission_registry import REGISTRY, STAFF_ONLY_KEYS
        p = REGISTRY['manage_customer_onboarding']
        self.assertTrue(p.staff_only)
        self.assertFalse(p.customer_assignable)
        self.assertIn('manage_customer_onboarding', STAFF_ONLY_KEYS)
        self.assertFalse(RoleTemplate._meta.get_field('manage_customer_onboarding').default)

    def test_role_seeds(self):
        from accounts import role_seeds
        by_key = {d.key: d for d in role_seeds.definitions()}
        self.assertTrue(by_key['org_owner'].flags['manage_customer_onboarding'])
        self.assertTrue(by_key['org_admin'].flags['manage_customer_onboarding'])
        for key in ('sales_rep', 'billing_frequency', 'auditor', 'customer_admin', 'tech_l1'):
            if key in by_key:
                self.assertFalse(by_key[key].flags.get('manage_customer_onboarding'), key)

    def test_legacy_simple_roles_keep_access(self):
        from accounts.models import Role, derive_legacy_flags
        from types import SimpleNamespace
        admin = derive_legacy_flags(SimpleNamespace(org_manage_settings=True), Role.ADMIN)
        reader = derive_legacy_flags(SimpleNamespace(org_manage_settings=False), Role.READONLY)
        self.assertTrue(admin.manage_customer_onboarding)
        self.assertFalse(reader.manage_customer_onboarding)

    def test_user_without_the_flag_cannot_start_or_apply(self):
        plain = make_staff('plain', manage_customer_onboarding=False)
        with self.assertRaises(StepError):
            engine.create_session(plain, S.NEW_CUSTOMER, self.tenant)
        s = self.new_session()
        with self.assertRaises(StepError):
            engine.apply_step(s, 'customer', {'mode': 'new', 'name': 'X'}, plain)

    def test_customer_user_never_holds_it(self):
        cust = User.objects.create_user('cust', 'c@example.com', 'pw')
        role = RoleTemplate.objects.create(name='cust role', manage_customer_onboarding=True)
        Membership.objects.create(user=cust, organization=self.tenant, role='owner', role_template=role,
                                  is_active=True)
        self.assertFalse(access.can_use(cust, self.tenant))
        self.assertFalse(access.is_staff(cust))

    def test_each_step_enforces_the_permission_of_the_thing_it_changes(self):
        s = self.new_session()
        self.customer(s)
        cases = {'locations': 'assets_create', 'contract_template': 'contracts_edit_draft',
                 'sla': 'org_manage_settings', 'accounting_mapping': 'integrations_configure',
                 'rmm': 'integrations_configure', 'activate': 'org_manage_settings'}
        for step_key, flag in cases.items():
            weak = make_staff(f'no_{step_key}', **{flag: False})
            step = registry.get_step(step_key)
            self.assertTrue(step.permission_denial(weak, s), step_key)
            self.assertEqual(step.permission_denial(self.tech, s), '', step_key)


class TenantIsolationTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org_a = Organization.objects.create(name='Org A', slug='org-a')
        cls.org_b = Organization.objects.create(name='Org B', slug='org-b')
        cls.a_tech = make_staff('a_tech', scope=[cls.org_a])
        cls.b_tech = make_staff('b_tech', scope=[cls.org_b])
        cls.b_session = engine.create_session(cls.b_tech, S.NEW_CUSTOMER, cls.org_b)
        cls.b_client = Organization.objects.create(name='B Client', slug='b-client', parent=cls.org_b)
        cls.b_change = engine.create_session(cls.b_tech, S.ADD_USERS, cls.org_b, cls.org_b)

    def test_scoped_staff_cannot_create_in_another_tenant(self):
        with self.assertRaises(StepError):
            engine.create_session(self.a_tech, S.NEW_CUSTOMER, self.org_b)
        with self.assertRaises(StepError):
            engine.create_session(self.a_tech, S.ADD_USERS, self.org_a, self.org_b)

    def test_sessions_listing_and_lookup_are_scoped(self):
        self.assertEqual(list(access.sessions_for(self.a_tech)), [])
        self.assertIn(self.b_session, access.sessions_for(self.b_tech))
        from django.http import Http404
        with self.assertRaises(Http404):
            access.session_for_user(self.a_tech, self.b_session.pk)

    def test_cannot_apply_skip_or_cancel_another_tenants_session(self):
        for call in (lambda: engine.apply_step(self.b_session, 'customer', {'mode': 'new', 'name': 'Hijack'},
                                               self.a_tech),
                     lambda: engine.skip_step(self.b_session, 'quantities', self.a_tech),
                     lambda: engine.cancel_session(self.b_session, self.a_tech),
                     lambda: engine.reopen_step(self.b_session, 'customer', self.a_tech)):
            with self.assertRaises(StepError):
                call()
        self.b_session.refresh_from_db()
        self.assertEqual(self.b_session.status, S.DRAFT)
        self.assertFalse(Organization.objects.filter(name='Hijack').exists())

    def test_customer_picker_only_offers_reachable_customers(self):
        self.assertEqual(list(access.reachable_clients(self.a_tech)), [self.org_a])

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_idor_over_http_is_a_404(self):
        self.client.force_login(self.a_tech)
        for url in (reverse('onboarding:session', args=[self.b_session.pk]),
                    reverse('onboarding:step', args=[self.b_session.pk, 'customer'])):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        for name, args in (('onboarding:step', [self.b_session.pk, 'customer']),
                           ('onboarding:skip', [self.b_session.pk, 'quantities']),
                           ('onboarding:reopen', [self.b_session.pk, 'customer']),
                           ('onboarding:cancel', [self.b_session.pk])):
            resp = self.client.post(reverse(name, args=args), {'mode': 'new', 'name': 'Hijack'})
            self.assertEqual(resp.status_code, 404, name)
        self.b_session.refresh_from_db()
        self.assertEqual(self.b_session.status, S.DRAFT)

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_start_listing_does_not_show_other_tenants_sessions(self):
        self.client.force_login(self.a_tech)
        resp = self.client.get(reverse('onboarding:start'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Org B')

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_start_post_cannot_target_an_unreachable_customer(self):
        self.client.force_login(self.a_tech)
        resp = self.client.post(reverse('onboarding:start'), {'kind': S.ADD_USERS, 'client': self.org_b.pk})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(S.objects.filter(client=self.org_b, created_by=self.a_tech).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(Base):
    def setUp(self):
        self.client.force_login(self.tech)

    def test_start_page_lists_in_progress_sessions(self):
        s = self.new_session()
        resp = self.client.get(reverse('onboarding:start'))
        self.assertContains(resp, 'In progress')
        self.assertContains(resp, s.display_title)

    def test_start_post_begins_a_session_and_redirects_to_the_first_step(self):
        # a technician working inside the MSP organization
        resp = self.client.post(reverse('onboarding:start'), {'kind': 'new_customer'})
        s = S.objects.get(created_by=self.tech)
        self.assertRedirects(resp, reverse('onboarding:step', args=[s.pk, 'customer']))
        self.assertEqual(s.organization, self.tenant)

    def test_full_walkthrough_over_http_with_resume(self):
        s = self.new_session()
        url = reverse('onboarding:step', args=[s.pk, 'customer'])
        page = self.client.get(url)
        self.assertContains(page, 'Customer')
        self.assertContains(page, 'Progress is saved')  # the checklist sidebar and resume note
        resp = self.client.post(url, {'mode': 'new', 'name': 'HTTP Co', 'save_and_exit': '1'})
        self.assertRedirects(resp, reverse('onboarding:session', args=[s.pk]))
        s.refresh_from_db()
        self.assertEqual(s.client.name, 'HTTP Co')
        overview = self.client.get(reverse('onboarding:session', args=[s.pk]))
        self.assertContains(overview, 'HTTP Co')
        self.assertContains(overview, 'Continue')
        # skip over HTTP
        resp = self.client.post(reverse('onboarding:skip', args=[s.pk, 'locations']), {'note': 'later'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(s.step_states.get(step_key='locations').status, St.SKIPPED)
        # an unavailable pricing step renders its notice
        with without('pricing'):
            page = self.client.get(reverse('onboarding:step', args=[s.pk, 'service_plan']))
        self.assertContains(page, 'Available once the price book is enabled')

    def test_form_errors_re_render_the_step(self):
        s = self.new_session()
        resp = self.client.post(reverse('onboarding:step', args=[s.pk, 'customer']), {'mode': 'new', 'name': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Enter the customer name')

    def test_required_permission_gates_the_pages(self):
        plain = make_staff('plain2', manage_customer_onboarding=False)
        self.client.force_login(plain)
        self.assertEqual(self.client.get(reverse('onboarding:start')).status_code, 403)
        s = self.new_session()
        self.assertEqual(self.client.get(reverse('onboarding:session', args=[s.pk])).status_code, 403)

    def test_customer_users_are_kept_out_of_the_section(self):
        cust = User.objects.create_user('cust2', 'c2@example.com', 'pw')
        Membership.objects.create(user=cust, organization=self.tenant, role='owner', is_active=True)
        self.client.force_login(cust)
        self.assertEqual(self.client.get(reverse('onboarding:start')).status_code, 403)

    def test_cancel_over_http(self):
        s = self.new_session()
        resp = self.client.post(reverse('onboarding:cancel', args=[s.pk]))
        self.assertEqual(resp.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.status, S.CANCELLED)

    def test_get_does_not_change_anything(self):
        s = self.new_session()
        for name in ('cancel', 'skip'):
            args = [s.pk] if name == 'cancel' else [s.pk, 'quantities']
            self.assertEqual(self.client.get(reverse(f'onboarding:{name}', args=args)).status_code, 405)

    def test_start_change_button_on_the_client_page(self):
        org = Organization.objects.create(name='Button Co', slug='button-co')
        page = self.client.get(reverse('accounts:organization_detail', args=[org.pk]))
        self.assertContains(page, 'Start change')
        self.assertContains(page, f'{reverse("onboarding:start")}?client={org.pk}')
        plain = make_staff('plain3', manage_customer_onboarding=False)
        self.client.force_login(plain)
        page = self.client.get(reverse('accounts:organization_detail', args=[org.pk]))
        self.assertNotContains(page, 'Start change')

    def test_lifecycle_start_from_the_client_page_preselects_the_customer(self):
        org = Organization.objects.create(name='Pre Co', slug='pre-co')
        page = self.client.get(reverse('onboarding:start') + f'?client={org.pk}')
        self.assertContains(page, f'value="{org.pk}" selected')
        resp = self.client.post(reverse('onboarding:start'), {'kind': 'add_users', 'client': org.pk})
        s = S.objects.get(kind='add_users')
        self.assertRedirects(resp, reverse('onboarding:step', args=[s.pk, 'change_details']))
        self.assertEqual(s.client, org)

    def test_navigation_has_one_onboard_entry_in_clients(self):
        from core import navigation
        tabs = [t for sec in navigation.SECTIONS if sec.key == 'clients_all' for t in sec.tabs]
        self.assertEqual([t.url_name for t in tabs if t.url_name.startswith('onboarding:')], ['onboarding:start'])
