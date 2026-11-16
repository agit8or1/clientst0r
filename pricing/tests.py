"""Pricing: price books, service plans, labor rate cards, resolvers, snapshots,
tenant isolation and cost-visibility gating."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase

from core.models import Organization
from psa.models import Contract, ContractBundleItem, Quote, QuoteLineItem, QuoteSignature
from pricing import services
from pricing.models import (
    BillingRule, ClientServicePlan, CustomerPriceOverride, LaborRole, PriceBook, PriceBookItem,
    PriceChangeHistory, PriceTier, RateCard, RateCardLine, ScheduledPriceChange, ServicePlan,
    ServicePlanEntitlement, ServicePlanItem,
)
from resourcing.models import TechCostRate, UserSkill

D = Decimal
TODAY = date(2026, 11, 16)


def _staff(user, role=None):
    from accounts.models import UserProfile, UserType
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    profile.save()
    user.is_staff = True
    user.save()
    return user


class Base(TestCase):
    """One install = one MSP. client_org (A) and client_b are two customers.
    Price book, roles and the default rate card are install-wide."""
    def setUp(self):
        self.client_org = Organization.objects.create(name='Customer A', slug='pr-cust-a')
        self.client_b = Organization.objects.create(name='Customer B', slug='pr-cust-b')
        self.tech = User.objects.create_user('pr-tech', password='pw')
        self.contract = Contract.objects.create(
            organization=self.client_org, client_org=self.client_org, name='MS', status='active',
            contract_type='managed_services', start_date=TODAY - timedelta(days=30))
        self.contract_b = Contract.objects.create(
            organization=self.client_b, client_org=self.client_b, name='MS B', status='active',
            contract_type='managed_services', start_date=TODAY - timedelta(days=30))
        self.role = LaborRole.objects.create(name='Help desk', code='T1')
        self.book = PriceBook.objects.create(name='Standard')
        self.item = PriceBookItem.objects.create(
            price_book=self.book, sku='AV-1', name='Managed AV', item_type='security',
            pricing_model='per_device', cost=D('3.00'), default_price=D('8.00'), minimum_price=D('6.00'))

    def card(self, rate, client=None, contract=None, role='self', rate_type='standard', **card_kw):
        card = RateCard.objects.create(name=f'card {rate}', client_org=client, contract=contract, **card_kw)
        line = RateCardLine.objects.create(rate_card=card, role=self.role if role == 'self' else role,
                                           rate_type=rate_type, hourly_rate=D(rate))
        return card, line


# ---------------------------------------------------------------------------
# Labor rate precedence
# ---------------------------------------------------------------------------

class LaborRatePrecedenceTests(Base):
    def resolve(self, **kw):
        defaults = dict(technician=self.tech, client=self.client_org, contract=self.contract, role=self.role,
                        on_date=TODAY)
        defaults.update(kw)
        return services.resolve_labor_rate(**defaults)

    def test_each_level_in_order(self):
        self.role.default_bill_rate = D('95')
        self.role.save()
        cc, _ = self.card('140', client=self.client_org, contract=self.contract)
        cu, _ = self.card('130', client=self.client_org)
        co, _ = self.card('120', contract=self.contract)
        de, _ = self.card('110')
        expected = [(cc, '140', 'customer_contract'), (cu, '130', 'customer'), (co, '120', 'contract'),
                    (de, '110', 'default')]
        for card, rate, source in expected:
            r = self.resolve()
            self.assertFalse(r.missing)
            self.assertEqual((r.rate, r.source, r.rate_card), (D(rate), source, card))
            card.is_active = False
            card.save()
        r = self.resolve()
        self.assertEqual((r.rate, r.source), (D('95'), 'role_default'))
        self.role.default_bill_rate = None
        self.role.save()
        r = self.resolve()
        self.assertTrue(r.missing)
        self.assertIsNone(r.rate)
        self.assertIn('no configured default rate', r.reason)

    def test_scopes_are_derived(self):
        self.assertEqual(self.card('1', client=self.client_org, contract=self.contract)[0].scope,
                         'customer_contract')
        self.assertEqual(self.card('1', client=self.client_org)[0].scope, 'customer')
        self.assertEqual(self.card('1', contract=self.contract)[0].scope, 'contract')
        self.assertEqual(self.card('1')[0].scope, 'default')

    def test_missing_never_invents_a_number(self):
        r = self.resolve()
        self.assertTrue(r.missing)
        self.assertIsNone(r.rate)
        self.assertNotIn(r.rate, (D('150'), D('60')))

    def test_rate_type_does_not_fall_back_to_standard(self):
        self.card('110')
        r = self.resolve(rate_type='emergency')
        self.assertTrue(r.missing)
        self.assertIn('emergency', r.reason)
        self.card('200', rate_type='emergency')
        self.assertEqual(self.resolve(rate_type='emergency').rate, D('200'))

    def test_customer_card_without_contract(self):
        self.card('130', client=self.client_org)
        r = self.resolve(contract=None)
        self.assertEqual(r.rate, D('130'))

    def test_effective_dating(self):
        self.card('100', effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30))
        self.card('120', effective_from=date(2026, 7, 1))
        self.assertEqual(self.resolve(on_date=date(2026, 3, 1)).rate, D('100'))
        self.assertEqual(self.resolve(on_date=date(2026, 7, 1)).rate, D('120'))
        self.assertTrue(self.resolve(on_date=date(2025, 12, 31)).missing)

    def test_latest_card_wins_within_a_level(self):
        self.card('100', effective_from=date(2026, 1, 1))
        self.card('105', effective_from=date(2026, 9, 1))
        self.assertEqual(self.resolve().rate, D('105'))

    def test_most_specific_line_wins(self):
        card, _ = self.card('110')
        RateCardLine.objects.create(rate_card=card, role=None, rate_type='standard', hourly_rate=D('90'))
        RateCardLine.objects.create(rate_card=card, role=self.role, rate_type='standard',
                                    technician=self.tech, hourly_rate=D('125'))
        self.assertEqual(self.resolve().rate, D('125'))
        other = User.objects.create_user('pr-other')
        self.assertEqual(self.resolve(technician=other).rate, D('110'))
        self.assertEqual(self.resolve(role=None).rate, D('90'))

    def test_skill_qualifier(self):
        card, _ = self.card('110')
        RateCardLine.objects.create(rate_card=card, role=self.role, rate_type='standard', skill='Cisco',
                                    hourly_rate=D('160'))
        self.assertEqual(self.resolve().rate, D('110'))
        UserSkill.objects.create(user=self.tech, name='cisco')
        self.assertEqual(self.resolve().rate, D('160'))


class CustomerIsolationTests(Base):
    """Customer A never resolves customer B's overrides, rates, plans or own books."""

    def test_other_customers_rate_cards_do_not_apply(self):
        self.card('999', client=self.client_b)
        self.card('888', contract=self.contract_b)
        self.card('777', client=self.client_b, contract=self.contract_b)
        r = services.resolve_labor_rate(technician=self.tech, client=self.client_org, contract=self.contract,
                                        role=self.role, on_date=TODAY)
        self.assertTrue(r.missing)
        self.card('110')
        r = services.resolve_labor_rate(client=self.client_org, contract=self.contract, role=self.role,
                                        on_date=TODAY)
        self.assertEqual((r.rate, r.source), (D('110'), 'default'))
        r = services.resolve_labor_rate(client=self.client_b, contract=self.contract_b, role=self.role,
                                        on_date=TODAY)
        self.assertEqual(r.rate, D('777'))

    def test_contract_of_another_customer_is_refused(self):
        self.card('110')
        r = services.resolve_labor_rate(client=self.client_org, contract=self.contract_b, role=self.role,
                                        on_date=TODAY)
        self.assertTrue(r.missing)
        self.assertIn('different customer', r.reason)
        r = services.resolve_price(self.item, client=self.client_org, contract=self.contract_b, on_date=TODAY)
        self.assertTrue(r.missing)
        self.assertIsNone(services.resolve_billing_rule(client=self.client_org, contract=self.contract_b))

    def test_other_customers_override_does_not_apply(self):
        CustomerPriceOverride.objects.create(client_org=self.client_b, item=self.item, unit_price=D('1.00'))
        r = services.resolve_price(self.item, client=self.client_org, on_date=TODAY)
        self.assertEqual((r.unit_price, r.source), (D('8.00'), 'price_book'))
        self.assertEqual(services.resolve_price(self.item, client=self.client_b, on_date=TODAY).unit_price,
                         D('1.00'))
        # No customer: never a customer override.
        self.assertEqual(services.resolve_price(self.item, on_date=TODAY).source, 'price_book')

    def test_customer_own_book_and_role_only_for_that_customer(self):
        own_book = PriceBook.objects.create(organization=self.client_b, name='B special')
        own_item = PriceBookItem.objects.create(price_book=own_book, sku='B-1', name='B only',
                                                default_price=D('3'))
        self.assertTrue(services.resolve_price(own_item, client=self.client_org, on_date=TODAY).missing)
        self.assertTrue(services.resolve_price(own_item, on_date=TODAY).missing)
        self.assertEqual(services.resolve_price(own_item, client=self.client_b, on_date=TODAY).unit_price, D('3'))
        own_role = LaborRole.objects.create(organization=self.client_b, name='B role', code='BX',
                                            default_bill_rate=D('50'))
        r = services.resolve_labor_rate(client=self.client_org, role=own_role, on_date=TODAY)
        self.assertTrue(r.missing)
        self.assertEqual(services.resolve_labor_rate(client=self.client_b, role=own_role, on_date=TODAY).rate,
                         D('50'))
        ov = CustomerPriceOverride(client_org=self.client_org, item=own_item, unit_price=D('1'))
        with self.assertRaises(ValidationError):
            ov.full_clean()

    def test_other_customers_plan_cannot_be_subscribed(self):
        b_plan = ServicePlan.objects.create(organization=self.client_b, name='B custom')
        csp = ClientServicePlan(client_org=self.client_org, plan=b_plan, start_date=TODAY)
        with self.assertRaises(ValidationError):
            csp.full_clean()
        ClientServicePlan(client_org=self.client_b, plan=b_plan, start_date=TODAY).full_clean()

    def test_install_wide_objects_are_unique_by_name_and_code(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceBook.objects.create(name='Standard')
        with self.assertRaises(IntegrityError), transaction.atomic():
            LaborRole.objects.create(name='Other', code='T1')
        # A customer's own book / role may reuse the name / code.
        PriceBook.objects.create(organization=self.client_b, name='Standard')
        LaborRole.objects.create(organization=self.client_b, name='Help desk', code='T1')


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

class PricePrecedenceTests(Base):
    def resolve(self, **kw):
        defaults = dict(client=self.client_org, contract=self.contract, on_date=TODAY, qty=10)
        defaults.update(kw)
        return services.resolve_price(self.item, **defaults)

    def test_each_level_in_order(self):
        cc = CustomerPriceOverride.objects.create(client_org=self.client_org,
                                                  item=self.item, contract=self.contract, unit_price=D('6.50'))
        cu = CustomerPriceOverride.objects.create(client_org=self.client_org,
                                                  item=self.item, unit_price=D('7.00'))
        r = self.resolve()
        self.assertEqual((r.unit_price, r.total, r.source), (D('6.50'), D('65.00'), 'customer_contract_override'))
        cc.is_active = False
        cc.save()
        r = self.resolve()
        self.assertEqual((r.unit_price, r.source), (D('7.00'), 'customer_override'))
        cu.is_active = False
        cu.save()
        r = self.resolve()
        self.assertEqual((r.unit_price, r.source, r.list_price), (D('8.00'), 'price_book', D('8.00')))

    def test_markup_override(self):
        CustomerPriceOverride.objects.create(client_org=self.client_org, item=self.item,
                                             markup_pct=D('50'))
        self.assertEqual(self.resolve().unit_price, D('4.5000'))
        self.item.cost = None
        self.item.save()
        r = self.resolve()
        self.assertTrue(r.missing)
        self.assertIn('no cost', r.reason)

    def test_override_xor_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerPriceOverride.objects.create(client_org=self.client_org,
                                                 item=self.item, unit_price=D('1'), markup_pct=D('5'))

    def test_no_list_price_is_missing(self):
        self.item.default_price = None
        self.item.save()
        r = self.resolve()
        self.assertTrue(r.missing)
        self.assertIsNone(r.unit_price)

    def test_below_minimum_is_flagged(self):
        CustomerPriceOverride.objects.create(client_org=self.client_org, item=self.item,
                                             unit_price=D('5.00'))
        r = self.resolve()
        self.assertTrue(r.below_minimum)
        self.assertFalse(r.missing)

    def test_effective_dating_and_inactive(self):
        self.item.effective_from = date(2026, 12, 1)
        self.item.save()
        self.assertTrue(self.resolve().missing)
        self.assertFalse(self.resolve(on_date=date(2026, 12, 1)).missing)
        ov = CustomerPriceOverride.objects.create(client_org=self.client_org,
                                                  item=self.item, unit_price=D('7'),
                                                  effective_to=date(2026, 12, 31))
        self.assertEqual(self.resolve(on_date=date(2026, 12, 15)).override, ov)
        self.assertEqual(self.resolve(on_date=date(2027, 1, 1)).source, 'price_book')
        self.book.is_active = False
        self.book.save()
        self.assertTrue(self.resolve(on_date=date(2026, 12, 15)).missing)

    def test_scheduled_change_is_used_from_its_date_and_applied(self):
        ScheduledPriceChange.objects.create(item=self.item, field='default_price', new_value=D('9.00'),
                                            effective_date=date(2027, 1, 1))
        self.assertEqual(self.resolve().unit_price, D('8.00'))
        self.assertEqual(self.resolve(on_date=date(2027, 1, 1)).unit_price, D('9.00'))
        self.assertEqual(ScheduledPriceChange.apply_due(on_date=TODAY), 0)
        self.assertEqual(ScheduledPriceChange.apply_due(on_date=date(2027, 1, 1)), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.default_price, D('9.00'))
        h = PriceChangeHistory.objects.filter(price_book_item=self.item, field='default_price').first()
        self.assertEqual((h.old_value, h.new_value, h.source), (D('8.00'), D('9.00'), 'scheduled'))


class TierMathTests(Base):
    def setUp(self):
        super().setUp()
        self.tiered = PriceBookItem.objects.create(price_book=self.book, sku='BK-T', name='Backup',
                                                   pricing_model='tiered')
        for lo, hi, price in ((1, 10, '10'), (11, 50, '8'), (51, None, '5')):
            PriceTier.objects.create(item=self.tiered, min_quantity=D(lo),
                                     max_quantity=D(hi) if hi else None, unit_price=D(price))

    def test_graduated(self):
        r = services.resolve_price(self.tiered, qty=12, on_date=TODAY)
        self.assertEqual(r.total, D('116.00'))           # 10 x 10 + 2 x 8
        self.assertEqual(r.source, 'tiers')
        self.assertEqual(services.resolve_price(self.tiered, qty=60, on_date=TODAY).total,
                         D('470.00'))                     # 100 + 40 x 8 + 10 x 5
        self.assertEqual(services.resolve_price(self.tiered, qty=10, on_date=TODAY).total, D('100.00'))

    def test_volume(self):
        self.tiered.pricing_model = 'volume'
        self.tiered.save()
        self.assertEqual(services.resolve_price(self.tiered, qty=12, on_date=TODAY).total, D('96.00'))
        self.assertEqual(services.resolve_price(self.tiered, qty=60, on_date=TODAY).total, D('300.00'))
        self.assertEqual(services.resolve_price(self.tiered, qty=5, on_date=TODAY).unit_price, D('10'))

    def test_gap_and_no_tiers_are_missing(self):
        self.tiered.tiers.filter(min_quantity=11).delete()
        r = services.resolve_price(self.tiered, qty=20, on_date=TODAY)
        self.assertTrue(r.missing)
        self.tiered.tiers.all().delete()
        r = services.resolve_price(self.tiered, qty=1, on_date=TODAY)
        self.assertTrue(r.missing)
        self.assertIn('no tiers', r.reason)

    def test_fractional_quantity(self):
        r = services.resolve_price(self.tiered, qty=D('10.5'), on_date=TODAY)
        self.assertEqual(r.total, D('104.00'))


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

class LineSnapshotTests(Base):
    def _quote(self, status='draft'):
        return Quote.objects.create(organization=self.client_org, client_org=self.client_org, title='Q', status=status)

    def test_quote_line_snapshot_survives_price_book_changes(self):
        quote = self._quote(status='accepted')
        line = QuoteLineItem(quote=quote, quantity=D('10'))
        res = services.apply_price_to_line(line, self.item, client=self.client_org, on_date=TODAY)
        line.save()
        self.assertFalse(res.missing)
        self.assertEqual((line.unit_price, line.unit_cost, line.list_price_snapshot),
                         (D('8.00'), D('3.00'), D('8.00')))
        self.assertEqual(line.description, 'Managed AV')
        # Signed: content hash locks the lines.
        QuoteSignature.objects.create(quote=quote, signed_by_name='C', signed_by_email='c@example.com',
                                      content_hash='a' * 64)
        self.item.default_price = D('12.00')
        self.item.cost = D('5.00')
        self.item.save()
        ScheduledPriceChange.objects.create(item=self.item, field='default_price', new_value=D('20'),
                                            effective_date=TODAY)
        ScheduledPriceChange.apply_due(on_date=TODAY)
        line.refresh_from_db()
        self.assertEqual((line.unit_price, line.unit_cost, line.list_price_snapshot),
                         (D('8.00'), D('3.00'), D('8.00')))
        self.assertEqual(line.price_book_item, self.item)

    def test_active_contract_bundle_keeps_snapshot(self):
        bundle = ContractBundleItem(contract=self.contract, quantity=D('25'))
        services.apply_price_to_line(bundle, self.item, client=self.client_org, contract=self.contract,
                                     on_date=TODAY)
        bundle.save()
        self.assertEqual(bundle.name, 'Managed AV')
        self.item.default_price = D('99.00')
        self.item.save()
        PriceBook.objects.filter(pk=self.book.pk).update(is_active=False)
        bundle.refresh_from_db()
        self.assertEqual((bundle.unit_price, bundle.list_price_snapshot), (D('8.00'), D('8.00')))

    def test_missing_price_leaves_unit_price_alone(self):
        self.item.default_price = None
        self.item.save()
        line = QuoteLineItem(quote=self._quote(), quantity=D('1'), unit_price=D('4.00'), description='x')
        res = services.apply_price_to_line(line, self.item, on_date=TODAY)
        self.assertTrue(res.missing)
        self.assertEqual(line.unit_price, D('4.00'))
        self.assertEqual(line.price_source, 'pricing:missing')

    def test_lines_without_price_book_unchanged(self):
        line = QuoteLineItem.objects.create(quote=self._quote(), description='Manual', unit_price=D('5'))
        self.assertIsNone(line.price_book_item)
        self.assertIsNone(line.unit_cost)
        self.assertEqual(line.line_total, D('5.00'))


class HistoryTests(Base):
    def test_item_create_and_change_are_recorded(self):
        self.assertTrue(PriceChangeHistory.objects.filter(price_book_item=self.item, field='cost',
                                                          old_value__isnull=True).exists())
        user = User.objects.create_user('pr-editor')
        self.item.default_price = D('8.50')
        self.item.save(_changed_by=user)
        h = PriceChangeHistory.objects.filter(price_book_item=self.item, field='default_price').first()
        self.assertEqual((h.old_value, h.new_value, h.changed_by), (D('8.00'), D('8.50'), user))
        self.assertIsNone(h.organization_id)        # install-wide book

    def test_unchanged_save_records_nothing(self):
        n = PriceChangeHistory.objects.count()
        self.item.name = 'Renamed'
        self.item.save()
        self.assertEqual(PriceChangeHistory.objects.count(), n)

    def test_append_only(self):
        h = PriceChangeHistory.objects.first()
        h.new_value = D('1')
        with self.assertRaises(ValidationError):
            h.save()
        with self.assertRaises(ValidationError):
            h.delete()

    def test_rate_line_and_override_changes_recorded(self):
        _, line = self.card('110')
        line.hourly_rate = D('115')
        line.save()
        self.assertTrue(PriceChangeHistory.objects.filter(object_type='pricing.ratecardline', object_id=line.pk,
                                                          new_value=D('115')).exists())
        ov = CustomerPriceOverride.objects.create(client_org=self.client_org,
                                                  item=self.item, unit_price=D('7'))
        self.assertTrue(PriceChangeHistory.objects.filter(object_type='pricing.customerpriceoverride',
                                                          object_id=ov.pk, field='unit_price').exists())


class PriceBookTests(Base):
    def test_duplicate_copies_items_and_tiers(self):
        PriceTier.objects.create(item=self.item, min_quantity=D('1'), unit_price=D('8'))
        copy = self.book.duplicate(name='2027')
        self.assertFalse(copy.is_active)
        self.assertEqual(copy.copied_from, self.book)
        c_item = copy.items.get(sku='AV-1')
        self.assertNotEqual(c_item.pk, self.item.pk)
        self.assertEqual(c_item.default_price, D('8.00'))
        self.assertEqual(c_item.tiers.count(), 1)
        self.assertEqual(self.book.items.count(), 1)

    def test_sku_unique_per_book(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceBookItem.objects.create(price_book=self.book, sku='AV-1', name='dup')
        other = PriceBook.objects.create(name='Other')
        PriceBookItem.objects.create(price_book=other, sku='AV-1', name='fine')

    def test_one_default_book(self):
        self.book.is_default = True
        self.book.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceBook.objects.create(name='B2', is_default=True)
        PriceBook.objects.create(organization=self.client_b, name='B own', is_default=True)

    def test_currency_falls_back_to_book(self):
        self.book.currency = 'EUR'
        self.book.save()
        self.assertEqual(self.item.effective_currency, 'EUR')


# ---------------------------------------------------------------------------
# Service plans
# ---------------------------------------------------------------------------

class ServicePlanTests(Base):
    def setUp(self):
        super().setUp()
        self.plan = ServicePlan.objects.create(name='Complete', per_user_price=D('120'))
        self.addon = ServicePlan.objects.create(name='Backup add-on', is_addon=True)

    def test_one_live_primary_many_addons(self):
        ClientServicePlan.objects.create(client_org=self.client_org, plan=self.plan,
                                         status='active', start_date=TODAY)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClientServicePlan.objects.create(client_org=self.client_org, plan=self.plan,
                                             status='pending', start_date=TODAY)
        for _ in range(2):
            ClientServicePlan.objects.create(client_org=self.client_org, plan=self.addon,
                                             role='addon', status='active', start_date=TODAY)
        ClientServicePlan.objects.create(client_org=self.client_org, plan=self.plan,
                                         status='ended', start_date=TODAY - timedelta(days=400))

    def test_role_must_match_plan_kind(self):
        csp = ClientServicePlan(client_org=self.client_org, plan=self.addon,
                                role='primary', start_date=TODAY)
        with self.assertRaises(ValidationError):
            csp.full_clean()

    def test_negotiated_price_and_contents(self):
        csp = ClientServicePlan.objects.create(client_org=self.client_org, plan=self.plan,
                                               start_date=TODAY, per_user_price=D('110'), users=20)
        self.assertEqual(csp.effective('per_user_price'), D('110'))
        self.assertIsNone(csp.effective('per_device_price'))
        ServicePlanItem.objects.create(plan=self.plan, item=self.item, quantity=D('1'), per_unit_of_plan=True)
        ent = ServicePlanEntitlement.objects.create(plan=self.plan, key='qbr', name='Quarterly review',
                                                    quantity=D('1'), unit='count', period='quarter')
        self.assertIn('NOT a permission', ServicePlanEntitlement.__doc__)
        self.assertEqual(self.plan.entitlements.get(), ent)

    def test_plan_price_change_recorded(self):
        self.plan.per_user_price = D('125')
        self.plan.save()
        self.assertTrue(PriceChangeHistory.objects.filter(object_type='pricing.serviceplan',
                                                          field='per_user_price', new_value=D('125')).exists())


# ---------------------------------------------------------------------------
# Billing rules / cost rates
# ---------------------------------------------------------------------------

class BillingRuleTests(Base):
    def test_rounding(self):
        rule = BillingRule(name='r', minimum_billable_minutes=15, increment_minutes=15,
                           rounding_mode='up')
        self.assertEqual([rule.billable_minutes(m) for m in (0, 5, 16, 30)], [0, 15, 30, 30])
        rule.rounding_mode = 'nearest'
        self.assertEqual([rule.billable_minutes(m) for m in (20, 23, 37)], [15, 30, 30])
        rule.rounding_mode = 'down'
        self.assertEqual(rule.billable_minutes(29), 15)
        rule.rounding_mode = 'none'
        self.assertEqual(rule.billable_minutes(29), 29)

    def test_resolution_precedence(self):
        self.assertIsNone(services.resolve_billing_rule(client=self.client_org, contract=self.contract))
        default = BillingRule.objects.create(name='default')
        self.assertEqual(services.resolve_billing_rule(client=self.client_org, contract=self.contract), default)
        BillingRule.objects.create(name='theirs', client_org=self.client_b)
        self.assertEqual(services.resolve_billing_rule(client=self.client_org, contract=self.contract), default)
        cust = BillingRule.objects.create(name='cust', client_org=self.client_org)
        self.assertEqual(services.resolve_billing_rule(client=self.client_org, contract=self.contract), cust)
        cc = BillingRule.objects.create(name='cc', client_org=self.client_org, contract=self.contract)
        self.assertEqual(services.resolve_billing_rule(client=self.client_org, contract=self.contract), cc)


class CostRateTests(Base):
    def test_unknown_instead_of_default(self):
        r = services.resolve_cost_rate(self.tech, TODAY)
        self.assertTrue(r.unknown)
        self.assertIsNone(r.rate)
        # Legacy behaviour unchanged for existing callers.
        self.assertEqual(TechCostRate.rate_for(self.tech, TODAY), D('60'))

    def test_burdened(self):
        row = TechCostRate.objects.create(user=self.tech, effective_from=TODAY - timedelta(days=1),
                                          base_hourly=D('40'), payroll_tax_pct=D('7.65'),
                                          benefits_pct=D('20'), overhead_alloc=D('5'))
        self.assertEqual(row.fully_burdened, D('56.06'))   # 40 x 1.2765 + 5
        row.refresh_from_db()
        self.assertEqual(row.rate_per_hour, D('56.06'))
        r = services.resolve_cost_rate(self.tech, TODAY)
        self.assertEqual((r.rate, r.burdened, r.unknown), (D('56.06'), True, False))

    def test_plain_rate_and_effective_dating(self):
        TechCostRate.objects.create(user=self.tech, effective_from=date(2026, 1, 1), rate_per_hour=D('45'))
        TechCostRate.objects.create(user=self.tech, effective_from=date(2026, 10, 1), rate_per_hour=D('50'))
        self.assertEqual(services.resolve_cost_rate(self.tech, date(2026, 5, 1)).rate, D('45'))
        self.assertEqual(services.resolve_cost_rate(self.tech, TODAY).rate, D('50'))
        self.assertTrue(services.resolve_cost_rate(self.tech, date(2025, 5, 1)).unknown)


# ---------------------------------------------------------------------------
# Permissions / cost visibility
# ---------------------------------------------------------------------------

class PermissionTests(Base):
    def setUp(self):
        super().setUp()
        from accounts.models import RoleTemplate
        self.manager_role = RoleTemplate.objects.create(name='Pricing editor', organization=None,
                                                        pricing_manage_price_books=True)
        self.cost_role = RoleTemplate.objects.create(name='Pricing + costs', organization=None,
                                                     pricing_manage_price_books=True,
                                                     pricing_view_internal_cost_rates=True)
        self.editor = _staff(User.objects.create_user('pr-ed'), self.manager_role)
        self.costs = _staff(User.objects.create_user('pr-costs'), self.cost_role)

    def test_registry(self):
        from accounts import permission_registry as reg
        from accounts.models import RoleTemplate
        from pricing import permissions as perms
        for key in perms.ALL:
            p = reg.get(key)
            self.assertIsNotNone(p, key)
            self.assertTrue(p.staff_only)
            self.assertFalse(p.customer_assignable)
            self.assertFalse(RoleTemplate._meta.get_field(key).default)

    def test_builtin_roles(self):
        from accounts.models import RoleTemplate
        owner = RoleTemplate.objects.get(seed_key='org_owner')
        billing = RoleTemplate.objects.get(seed_key='billing_finance')
        sales_mgr = RoleTemplate.objects.get(seed_key='sales_manager')
        sales_rep = RoleTemplate.objects.get(seed_key='sales_rep')
        from pricing import permissions as perms
        for key in perms.ALL:
            self.assertTrue(getattr(owner, key), key)
            self.assertTrue(getattr(billing, key), key)
            self.assertFalse(getattr(sales_rep, key), key)
        self.assertTrue(sales_mgr.pricing_approve_discounts)
        self.assertFalse(sales_mgr.pricing_view_internal_cost_rates)
        for rt in (owner, billing, sales_mgr):
            self.assertEqual(rt.compute_checksum(), rt.seed_checksum, rt.name)

    def test_serializer_hides_costs(self):
        from pricing.serializers import item_to_dict, price_result_to_dict
        hidden = item_to_dict(self.item, self.editor)
        for f in PriceBookItem.COST_FIELDS:
            self.assertNotIn(f, hidden)
        self.assertEqual(hidden['default_price'], '8.00')
        shown = item_to_dict(self.item, self.costs)
        self.assertEqual(shown['cost'], '3.00')
        res = services.resolve_price(self.item, on_date=TODAY)
        self.assertNotIn('unit_cost', price_result_to_dict(res, self.editor, None))
        self.assertEqual(price_result_to_dict(res, self.costs, None)['unit_cost'], '3.00')

    def test_admin_hides_cost_fields(self):
        from django.contrib import admin as dj_admin
        model_admin = dj_admin.site._registry[PriceBookItem]
        rf = RequestFactory()
        req = rf.get('/admin/pricing/pricebookitem/')
        req.user = self.editor
        self.assertTrue(model_admin.has_change_permission(req, self.item))
        fields = model_admin.get_fields(req, self.item)
        for f in PriceBookItem.COST_FIELDS:
            self.assertNotIn(f, fields)
        self.assertNotIn('cost', model_admin.get_list_display(req))
        form = model_admin.get_form(req, self.item)
        self.assertNotIn('cost', form.base_fields)
        req.user = self.costs
        self.assertIn('cost', model_admin.get_fields(req, self.item))
        self.assertIn('cost', model_admin.get_form(req, self.item).base_fields)

    def test_admin_requires_pricing_permission(self):
        from django.contrib import admin as dj_admin
        model_admin = dj_admin.site._registry[PriceBookItem]
        nobody = _staff(User.objects.create_user('pr-nobody'), None)
        req = RequestFactory().get('/admin/')
        req.user = nobody
        self.assertFalse(model_admin.has_module_permission(req))
        self.assertFalse(model_admin.has_change_permission(req, self.item))
        rate_admin = dj_admin.site._registry[RateCard]
        req.user = self.editor
        self.assertFalse(rate_admin.has_module_permission(req))   # needs manage_labor_rate_cards

    def test_admin_change_is_audited(self):
        from audit.models import AuditLog
        from django.contrib import admin as dj_admin
        model_admin = dj_admin.site._registry[PriceBookItem]
        req = RequestFactory().post('/admin/pricing/pricebookitem/1/change/')
        req.user = self.costs
        self.item.default_price = D('9.25')
        model_admin.save_model(req, self.item, None, True)
        log = AuditLog.objects.filter(object_type='pricing.PriceBookItem', object_id=self.item.pk).latest('pk')
        self.assertEqual(log.extra_data['price_changes']['default_price'], {'from': '8.00', 'to': '9.25'})
        h = PriceChangeHistory.objects.filter(price_book_item=self.item, field='default_price').first()
        self.assertEqual((h.changed_by, h.source), (self.costs, 'admin'))

    def test_below_minimum_override_needs_approval(self):
        from django.contrib import admin as dj_admin
        from django.core.exceptions import PermissionDenied
        model_admin = dj_admin.site._registry[CustomerPriceOverride]
        approver_role = self.manager_role
        req = RequestFactory().post('/admin/')
        req.user = self.editor
        ov = CustomerPriceOverride(client_org=self.client_org, item=self.item, unit_price=D('5'))
        with self.assertRaises(PermissionDenied):
            model_admin.save_model(req, ov, None, False)
        approver_role.pricing_approve_discounts = True
        approver_role.save()
        req.user = User.objects.get(pk=self.editor.pk)
        model_admin.save_model(req, ov, None, False)
        self.assertEqual(ov.approved_by_id, self.editor.pk)

    def test_admin_scope_install_wide_vs_customer_rows(self):
        """Install-wide books are visible to staff with the permission; a
        customer's overrides only within the staff member's client scope."""
        from django.contrib import admin as dj_admin
        from accounts.models import UserProfile
        CustomerPriceOverride.objects.create(client_org=self.client_org, item=self.item, unit_price=D('7'))
        ov_b = CustomerPriceOverride.objects.create(client_org=self.client_b, item=self.item, unit_price=D('7'))
        scoped = _staff(User.objects.create_user('pr-scoped'), self.manager_role)
        profile = UserProfile.objects.get(user=scoped)
        profile.client_scope = 'selected'
        profile.save()
        profile.scope_organizations.add(self.client_org)
        scoped = User.objects.get(pk=scoped.pk)
        req = RequestFactory().get('/admin/')
        req.user = scoped
        books = dj_admin.site._registry[PriceBook].get_queryset(req)
        self.assertIn(self.book, books)
        ovs = dj_admin.site._registry[CustomerPriceOverride].get_queryset(req)
        self.assertEqual({o.client_org_id for o in ovs}, {self.client_org.pk})
        self.assertFalse(dj_admin.site._registry[CustomerPriceOverride].has_change_permission(req, ov_b))
        self.assertTrue(dj_admin.site._registry[PriceBook].has_change_permission(req, self.book))
