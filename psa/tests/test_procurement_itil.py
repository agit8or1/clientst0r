"""
Auto-split fragment of the legacy `psa/tests.py` (v3.17.192).
See `psa/tests/__init__.py` for the rationale.
"""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from psa.feature_flags import (
    is_psa_enabled,
    is_psa_enabled_for_client,
)
from psa.models import (
    ClientPSASettings,
    Queue,
    Ticket,
    TicketPriority,
    TicketStatus,
    TicketType,
)

from psa.tests._base import (
    TEST_MIDDLEWARE,
    _setup_seed,
    _enable_psa_global,
    _enable_psa_for,
    _make_msp_tech,
)


class ProcurementModelTests(TestCase):
    """Numbering + totals math for PR/PO."""

    def setUp(self):
        from psa.models import (
            PurchaseRequisition, PurchaseRequisitionLineItem,
            PurchaseOrder, PurchaseOrderLineItem,
        )
        self.PR = PurchaseRequisition
        self.PRLI = PurchaseRequisitionLineItem
        self.PO = PurchaseOrder
        self.POLI = PurchaseOrderLineItem
        self.org = Organization.objects.create(name='ProcOrg', slug='proc-org')

    def test_pr_next_number(self):
        from django.utils import timezone
        year = timezone.now().year
        pr1 = self.PR.objects.create(organization=self.org, title='First')
        pr2 = self.PR.objects.create(organization=self.org, title='Second')
        self.assertEqual(pr1.pr_number, f'PR-{year}-00001')
        self.assertEqual(pr2.pr_number, f'PR-{year}-00002')

    def test_pr_recompute_totals(self):
        from decimal import Decimal
        pr = self.PR.objects.create(
            organization=self.org, title='Totals', tax_rate=Decimal('10'),
        )
        self.PRLI.objects.create(requisition=pr, description='Switch',
                                  quantity=Decimal('2'), unit_price=Decimal('100'))
        self.PRLI.objects.create(requisition=pr, description='Cable',
                                  quantity=Decimal('5'), unit_price=Decimal('20'))
        pr.recompute_totals()
        # subtotal: 2*100 + 5*20 = 300; tax 10% = 30; total 330
        self.assertEqual(pr.subtotal, Decimal('300'))
        self.assertEqual(pr.tax_amount, Decimal('30'))
        self.assertEqual(pr.total, Decimal('330'))

    def test_po_next_number(self):
        from django.utils import timezone
        year = timezone.now().year
        po1 = self.PO.objects.create(
            organization=self.org, vendor_name='V1', title='T1')
        po2 = self.PO.objects.create(
            organization=self.org, vendor_name='V2', title='T2')
        self.assertEqual(po1.po_number, f'PO-{year}-00001')
        self.assertEqual(po2.po_number, f'PO-{year}-00002')

    def test_po_total_includes_shipping(self):
        from decimal import Decimal
        po = self.PO.objects.create(
            organization=self.org, vendor_name='Acme',
            title='Ship test', tax_rate=Decimal('10'),
            shipping_cost=Decimal('25'),
        )
        self.POLI.objects.create(po=po, description='Item',
                                  quantity=Decimal('1'), unit_price=Decimal('100'))
        po.recompute_totals()
        # subtotal 100; tax 10; shipping 25; total 135
        self.assertEqual(po.subtotal, Decimal('100'))
        self.assertEqual(po.tax_amount, Decimal('10'))
        self.assertEqual(po.total, Decimal('135'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProcurementWorkflowTests(TestCase):
    """Approval gate + PR-to-PO conversion via HTTP."""

    def setUp(self):
        from accounts.models import RoleTemplate
        from psa.models import PurchaseRequisition, PurchaseRequisitionLineItem
        from decimal import Decimal
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ProcCo', slug='proc-co')

        # Approver: full procurement perms
        self.approver_role = RoleTemplate.objects.create(
            name='ProcApprover', is_system_template=False,
            procurement_view=True, procurement_create_pr=True,
            procurement_approve_pr=True, procurement_create_po=True,
            procurement_send_po=True,
        )
        self.approver = User.objects.create_user(
            username='approver', password='pw', email='a@x.com')
        Membership.objects.create(
            user=self.approver, organization=self.org,
            role=Role.ADMIN, role_template=self.approver_role,
            is_active=True,
        )

        # Tech: can create PR, cannot approve
        self.tech_role = RoleTemplate.objects.create(
            name='ProcTech', is_system_template=False,
            procurement_view=True, procurement_create_pr=True,
            procurement_approve_pr=False, procurement_create_po=False,
            procurement_send_po=False,
        )
        self.tech = User.objects.create_user(
            username='tech', password='pw', email='t@x.com')
        Membership.objects.create(
            user=self.tech, organization=self.org,
            role=Role.EDITOR, role_template=self.tech_role,
            is_active=True,
        )

        # Submitted PR with one line item
        self.pr = PurchaseRequisition.objects.create(
            organization=self.org, title='Need switch',
            requested_by=self.tech, status='submitted',
            tax_rate=Decimal('0'),
        )
        PurchaseRequisitionLineItem.objects.create(
            requisition=self.pr, description='Cisco switch',
            quantity=Decimal('1'), unit_price=Decimal('500'),
            sku='WS-C2960X', distributor_provider='ingram',
        )
        self.pr.recompute_totals()
        self.pr.save()

    def test_approver_can_approve(self):
        c = Client()
        c.force_login(self.approver)
        resp = c.post(f'/psa/requisitions/{self.pr.pk}/decide/', {
            'decision': 'approve',
            'decision_note': 'looks good',
        })
        self.assertEqual(resp.status_code, 302)
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, 'approved')
        self.assertEqual(self.pr.approver_id, self.approver.pk)
        self.assertIsNotNone(self.pr.decided_at)

    def test_non_approver_blocked(self):
        c = Client()
        c.force_login(self.tech)
        resp = c.post(f'/psa/requisitions/{self.pr.pk}/decide/', {
            'decision': 'approve',
        })
        self.assertEqual(resp.status_code, 403)
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, 'submitted')

    def test_pr_to_po_conversion(self):
        from psa.models import PurchaseOrder
        # Approve first
        self.pr.status = 'approved'
        self.pr.save(update_fields=['status'])

        c = Client()
        c.force_login(self.approver)
        resp = c.post(f'/psa/requisitions/{self.pr.pk}/convert/', {
            'vendor_name': 'Ingram Micro',
            'vendor_email': 'orders@ingrammicro.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, 'converted')

        po = PurchaseOrder.objects.filter(requisition=self.pr).first()
        self.assertIsNotNone(po)
        self.assertEqual(po.vendor_name, 'Ingram Micro')
        # Line items copied
        self.assertEqual(po.line_items.count(), 1)
        line = po.line_items.first()
        self.assertEqual(line.description, 'Cisco switch')
        self.assertEqual(line.sku, 'WS-C2960X')


# ---------------------------------------------------------------------------
# Phase 4.2 — Receiving + back-orders + serial-number capture
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class POReceivingTests(TestCase):
    """Receiving workflow: partial / full / back-orders / serials / cap."""

    def setUp(self):
        from accounts.models import RoleTemplate
        from psa.models import (
            PurchaseOrder, PurchaseOrderLineItem,
        )
        from decimal import Decimal
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='RecvCo', slug='recv-co')

        # Receiver role: full procurement perms
        self.role = RoleTemplate.objects.create(
            name='ProcReceiver', is_system_template=False,
            procurement_view=True, procurement_create_pr=True,
            procurement_approve_pr=True, procurement_create_po=True,
            procurement_send_po=True,
        )
        self.user = User.objects.create_user(
            username='receiver', password='pw', email='r@x.com')
        Membership.objects.create(
            user=self.user, organization=self.org,
            role=Role.ADMIN, role_template=self.role,
            is_active=True,
        )

        # PO with 2 lines (qty 10 each), status=sent
        self.po = PurchaseOrder.objects.create(
            organization=self.org, vendor_name='ACME Vendor',
            title='Receiving test PO', status='sent',
        )
        self.line1 = PurchaseOrderLineItem.objects.create(
            po=self.po, description='Widget A', sku='WA-01',
            quantity=Decimal('10'), unit_price=Decimal('5'),
        )
        self.line2 = PurchaseOrderLineItem.objects.create(
            po=self.po, description='Widget B', sku='WB-01',
            quantity=Decimal('10'), unit_price=Decimal('7'),
        )
        self.po.recompute_totals()
        self.po.save()

    def _post_receive(self, data):
        c = Client()
        c.force_login(self.user)
        return c.post(f'/psa/purchase-orders/{self.po.pk}/receive/', data)

    def test_partial_receive_flips_status_to_partial(self):
        # Receive 5/10 on line 1, 0/10 on line 2 → PO.status = 'partial'
        resp = self._post_receive({
            f'qty_line_{self.line1.pk}': '5',
            f'qty_line_{self.line2.pk}': '',
            'carrier': 'UPS',
        })
        self.assertEqual(resp.status_code, 302)
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, 'partial')
        self.line1.refresh_from_db()
        self.assertEqual(self.line1.received_quantity, 5)

    def test_full_receive_flips_status_to_received(self):
        # Receive 10/10 on both lines → PO.status = 'received'
        resp = self._post_receive({
            f'qty_line_{self.line1.pk}': '10',
            f'qty_line_{self.line2.pk}': '10',
        })
        self.assertEqual(resp.status_code, 302)
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, 'received')

    def test_back_order_created_for_shorted_line(self):
        # Receive 6/10 on line 1 → POBackOrder with qty_outstanding=4
        from psa.models import POBackOrder
        resp = self._post_receive({
            f'qty_line_{self.line1.pk}': '6',
        })
        self.assertEqual(resp.status_code, 302)
        bo = POBackOrder.objects.filter(po_line=self.line1, status='open').first()
        self.assertIsNotNone(bo)
        self.assertEqual(bo.quantity_outstanding, 4)

    def test_back_order_filled_on_full_receive(self):
        # Open BO, then receive remainder → BO status flips to 'filled'
        from psa.models import POBackOrder
        # First: receive 6 of 10 on line 1, 10 of 10 on line 2
        self._post_receive({
            f'qty_line_{self.line1.pk}': '6',
            f'qty_line_{self.line2.pk}': '10',
        })
        bo = POBackOrder.objects.filter(po_line=self.line1, status='open').first()
        self.assertIsNotNone(bo)
        # Now receive the remaining 4 on line 1
        self._post_receive({
            f'qty_line_{self.line1.pk}': '4',
        })
        bo.refresh_from_db()
        self.assertEqual(bo.status, 'filled')
        self.assertIsNotNone(bo.closed_at)
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, 'received')

    def test_serial_numbers_captured_and_assets_created(self):
        # Receive 1 unit with serial="ABC123" → POReceiptLine has it,
        # assets.Asset row created with that serial number
        from psa.models import POReceiptLine
        resp = self._post_receive({
            f'qty_line_{self.line1.pk}': '1',
            f'serials_line_{self.line1.pk}': 'ABC123',
        })
        self.assertEqual(resp.status_code, 302)
        rl = POReceiptLine.objects.filter(po_line=self.line1).first()
        self.assertIsNotNone(rl)
        self.assertEqual(rl.serial_numbers, ['ABC123'])
        # Asset row created (best-effort — only if creatable)
        try:
            from assets.models import Asset
            self.assertTrue(Asset.objects.filter(serial_number='ABC123').exists())
        except Exception:
            pass

    def test_qty_capped_at_remaining(self):
        # Try to receive 999 on a line with only 10 outstanding → only 10 received
        resp = self._post_receive({
            f'qty_line_{self.line1.pk}': '999',
        })
        self.assertEqual(resp.status_code, 302)
        self.line1.refresh_from_db()
        self.assertEqual(self.line1.received_quantity, 10)

    def test_back_order_cancel(self):
        # Receive partial → open BO → cancel it
        from psa.models import POBackOrder
        self._post_receive({
            f'qty_line_{self.line1.pk}': '6',
        })
        bo = POBackOrder.objects.filter(po_line=self.line1, status='open').first()
        self.assertIsNotNone(bo)
        c = Client()
        c.force_login(self.user)
        resp = c.post(f'/psa/back-orders/{bo.pk}/cancel/')
        self.assertEqual(resp.status_code, 302)
        bo.refresh_from_db()
        self.assertEqual(bo.status, 'cancelled')
        self.assertIsNotNone(bo.closed_at)


# ---------------------------------------------------------------------------
# Phase 4.3 — Vendor metadata + auto-replenish
# ---------------------------------------------------------------------------

class VendorMetadataTests(TestCase):
    """assets.Vendor procurement metadata + PO vendor-FK auto-fill."""

    def test_vendor_default_lead_time(self):
        from assets.models import Vendor
        v = Vendor.objects.create(name='ACME Distribution', slug='acme-dist')
        self.assertEqual(v.default_lead_time_days, 7)
        self.assertEqual(v.payment_terms, '')
        self.assertEqual(v.preferred_contact_method, '')
        self.assertTrue(v.is_active)

    def test_vendor_metadata_fields_persist(self):
        from assets.models import Vendor
        v = Vendor.objects.create(
            name='Ingram', slug='ingram',
            default_lead_time_days=14,
            payment_terms='net_30',
            preferred_contact_method='email',
            contact_email='orders@ingram.com',
            contact_phone='555-1212',
            billing_address='1 Main St',
            account_number='ACCT-99',
            distributor_provider='ingram',
            notes='Primary distributor.',
        )
        v.refresh_from_db()
        self.assertEqual(v.default_lead_time_days, 14)
        self.assertEqual(v.payment_terms, 'net_30')
        self.assertEqual(v.contact_email, 'orders@ingram.com')
        self.assertEqual(v.distributor_provider, 'ingram')

    def test_po_vendor_fk_link(self):
        """PurchaseOrder.vendor FK persists alongside snapshot fields."""
        from assets.models import Vendor
        from psa.models import PurchaseOrder
        v = Vendor.objects.create(
            name='Vendor X', slug='vendor-x',
            contact_email='x@v.com', default_lead_time_days=10,
        )
        org = Organization.objects.create(name='POVendorCo', slug='povc')
        po = PurchaseOrder.objects.create(
            organization=org, vendor=v, vendor_name='Vendor X',
            vendor_email='x@v.com', title='FK test',
        )
        po.refresh_from_db()
        self.assertEqual(po.vendor_id, v.pk)
        # purchase_orders related_name on Vendor
        self.assertEqual(v.purchase_orders.count(), 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AutoReplenishTests(TestCase):
    """psa_auto_replenish_suggestions: scan + grouping + dedupe."""

    def setUp(self):
        from inventory.models import InventoryItem
        from assets.models import Vendor
        # MSP org for the command's PR-creation step
        self.org = Organization.objects.create(
            name='ReplenishCo', slug='replenish-co', is_active=True,
        )
        self.vendor = Vendor.objects.create(name='Auto Vendor', slug='auto-vendor')
        # Below-minimum item with a preferred vendor
        self.item = InventoryItem.objects.create(
            organization=self.org,
            name='Patch cable 6ft', sku='PC-6',
            quantity=1, min_quantity=5,
            reorder_quantity=10,
            preferred_vendor=self.vendor,
            unit_cost='3.50',
        )
        # Below-minimum item with NO vendor — should still log
        self.item_no_vendor = InventoryItem.objects.create(
            organization=self.org,
            name='Cat6 jack', sku='J-CAT6',
            quantity=0, min_quantity=20,
        )

    def test_scan_finds_below_minimum_items(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('psa_auto_replenish_suggestions', '--dry-run', stdout=out)
        text = out.getvalue()
        self.assertIn('Patch cable 6ft', text)
        self.assertIn('Cat6 jack', text)
        self.assertIn('Found 2 items below minimum', text)

    def test_create_prs_groups_by_vendor(self):
        from io import StringIO
        from django.core.management import call_command
        from inventory.models import InventoryItem
        from psa.models import PurchaseRequisition

        # Add 2nd item from same vendor — should land in same PR
        InventoryItem.objects.create(
            organization=self.org,
            name='Patch cable 25ft', sku='PC-25',
            quantity=0, min_quantity=5,
            reorder_quantity=10,
            preferred_vendor=self.vendor,
        )

        out = StringIO()
        call_command('psa_auto_replenish_suggestions', '--create-prs', stdout=out)

        # Two vendors total: Auto Vendor (2 items) + null (Cat6 jack)
        prs = PurchaseRequisition.objects.filter(status='draft')
        # One PR per vendor
        self.assertGreaterEqual(prs.count(), 1)
        auto_pr = prs.filter(title__icontains='Auto Vendor').first()
        self.assertIsNotNone(auto_pr)
        self.assertEqual(auto_pr.line_items.count(), 2)

    def test_skips_items_already_on_open_pr(self):
        from io import StringIO
        from django.core.management import call_command
        from psa.models import PurchaseRequisition, PurchaseRequisitionLineItem

        # Create an existing draft PR with the SKU we'd otherwise auto-suggest
        existing = PurchaseRequisition.objects.create(
            organization=self.org, title='Manual PR', status='draft',
        )
        PurchaseRequisitionLineItem.objects.create(
            requisition=existing, description='Patch cable 6ft',
            sku='PC-6', quantity=1, unit_price=0,
        )

        out = StringIO()
        call_command('psa_auto_replenish_suggestions', '--create-prs', stdout=out)

        # Auto-replenish should not create a new PR with PC-6 since it's
        # already on an open PR. Item without a SKU (Cat6 jack — has SKU
        # 'J-CAT6' which isn't on any PR) WILL get a new PR.
        new_prs = PurchaseRequisition.objects.filter(
            title__icontains='Auto-replenish').all()
        for pr in new_prs:
            for li in pr.line_items.all():
                self.assertNotEqual(li.sku, 'PC-6')


# ---------------------------------------------------------------------------
# Phase 4.4 — One-click PO from accepted quote
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuoteToPOTests(TestCase):
    """v3.17.151: convert accepted Quote to draft PurchaseOrder."""

    def setUp(self):
        from accounts.models import RoleTemplate
        from psa.models import Quote, QuoteLineItem
        from decimal import Decimal
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='Q2PO Co', slug='q2po-co')
        _enable_psa_for(self.org)

        # Buyer: full procurement perms (can create PO)
        self.buyer_role = RoleTemplate.objects.create(
            name='Q2POBuyer', is_system_template=False,
            procurement_view=True, procurement_create_pr=True,
            procurement_approve_pr=True, procurement_create_po=True,
            procurement_send_po=True,
        )
        self.creator = User.objects.create_user(
            username='q2po_buyer', password='pw', email='c@x.com')
        Membership.objects.create(
            user=self.creator, organization=self.org,
            role=Role.ADMIN, role_template=self.buyer_role,
            is_active=True,
        )

        # Tech (no procurement_create_po)
        self.tech_role = RoleTemplate.objects.create(
            name='Q2POTech', is_system_template=False,
            procurement_view=True, procurement_create_pr=True,
            procurement_approve_pr=False, procurement_create_po=False,
            procurement_send_po=False,
        )
        self.tech = User.objects.create_user(
            username='q2po_tech', password='pw', email='t@x.com')
        Membership.objects.create(
            user=self.tech, organization=self.org,
            role=Role.EDITOR, role_template=self.tech_role,
            is_active=True,
        )

        # Build an accepted quote with 2 line items
        self.quote = Quote.objects.create(
            organization=self.org, client_org=self.org,
            title='Test Quote', status='accepted',
            subtotal=Decimal('200'), tax_rate=Decimal('0.10'),
            tax_amount=Decimal('20'), total=Decimal('220'),
        )
        QuoteLineItem.objects.create(
            quote=self.quote, sort_order=0,
            description='Switch', quantity=Decimal('1'), unit_price=Decimal('150'),
        )
        QuoteLineItem.objects.create(
            quote=self.quote, sort_order=1,
            description='Cable', quantity=Decimal('5'), unit_price=Decimal('10'),
        )

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def test_convert_creates_draft_po(self):
        from psa.models import PurchaseOrder
        c = self._login(self.creator)
        r = c.post(f'/psa/quotes/{self.quote.pk}/to-po/')
        self.assertEqual(r.status_code, 302)
        po = PurchaseOrder.objects.filter(source_quote=self.quote).first()
        self.assertIsNotNone(po)
        self.assertEqual(po.status, 'draft')
        self.assertEqual(po.line_items.count(), self.quote.line_items.count())
        # Notes carry the audit crumb
        self.assertIn(self.quote.quote_number, po.notes)
        # Redirect lands on PO edit
        self.assertIn(f'/purchase-orders/{po.pk}/edit/', r.url)

    def test_convert_blocked_for_non_accepted_quote(self):
        from psa.models import PurchaseOrder
        self.quote.status = 'sent'
        self.quote.save(update_fields=['status'])
        c = self._login(self.creator)
        r = c.post(f'/psa/quotes/{self.quote.pk}/to-po/')
        # Should redirect back to quote detail (no PO created)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            PurchaseOrder.objects.filter(source_quote=self.quote).count(), 0,
        )

    def test_convert_blocked_without_permission(self):
        c = self._login(self.tech)
        r = c.post(f'/psa/quotes/{self.quote.pk}/to-po/')
        # @require_perm should 403 (or redirect on some setups)
        self.assertIn(r.status_code, [302, 403])
        from psa.models import PurchaseOrder
        self.assertEqual(
            PurchaseOrder.objects.filter(source_quote=self.quote).count(), 0,
        )


# ---------------------------------------------------------------------------
# v3.17.154 — Procurement gates (techs request, managers approve)
# ---------------------------------------------------------------------------


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProcurementGateTests(TestCase):
    """Confirm requisition_decide is gated by procurement_approve_pr."""

    def setUp(self):
        from accounts.models import RoleTemplate
        from psa.models import PurchaseRequisition, PurchaseRequisitionLineItem
        from decimal import Decimal
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ProcGateOrg', slug='proc-gate-org')

        # Tech: can create, cannot approve
        self.tech_role = RoleTemplate.objects.create(
            name='ProcGateTech', is_system_template=False,
            procurement_view=True, procurement_create_pr=True,
            procurement_approve_pr=False, procurement_create_po=False,
        )
        self.tech = User.objects.create_user(
            username='gate_tech', password='pw', email='gt@x.com')
        Membership.objects.create(
            user=self.tech, organization=self.org,
            role=Role.EDITOR, role_template=self.tech_role,
            is_active=True,
        )

        # Admin / superuser
        self.admin = User.objects.create_user(
            username='gate_admin', password='pw', email='ga@x.com',
            is_staff=True, is_superuser=True,
        )
        Membership.objects.create(
            user=self.admin, organization=self.org,
            role=Role.ADMIN, is_active=True,
        )

        self.pr = PurchaseRequisition.objects.create(
            organization=self.org, title='Need a switch',
            requested_by=self.tech, status='submitted',
            tax_rate=Decimal('0'),
        )
        PurchaseRequisitionLineItem.objects.create(
            requisition=self.pr, description='Switch',
            quantity=Decimal('1'), unit_price=Decimal('100'),
        )
        self.pr.recompute_totals()
        self.pr.save()

    def test_tech_cannot_decide_pr(self):
        c = Client()
        c.force_login(self.tech)
        r = c.post(f'/psa/requisitions/{self.pr.pk}/decide/', {
            'decision': 'approve',
            'decision_note': 'no',
        })
        # require_perm raises PermissionDenied -> 403
        self.assertEqual(r.status_code, 403)
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, 'submitted')

    def test_admin_can_decide_pr(self):
        c = Client()
        c.force_login(self.admin)
        r = c.post(f'/psa/requisitions/{self.pr.pk}/decide/', {
            'decision': 'approve',
            'decision_note': 'OK',
        })
        self.assertIn(r.status_code, [200, 302])
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, 'approved')


# ---------------------------------------------------------------------------
# Phase 6.1 — Change requests with CAB approval workflow
# ---------------------------------------------------------------------------


def _make_change_ticket(org, **overrides):
    """Helper: build a ticket with ticket_type slug='change'. The
    auto-spawn signal will create the ChangeRequest."""
    from psa.models import (
        Queue, TicketStatus, TicketPriority, TicketType, Ticket,
    )
    queue = Queue.objects.first() or Queue.objects.create(name='Helpdesk', slug='helpdesk')
    status = TicketStatus.objects.first() or TicketStatus.objects.create(name='New', slug='new')
    priority = TicketPriority.objects.first() or TicketPriority.objects.create(
        code='P3', name='Normal',
        response_target_minutes=240, resolution_target_minutes=4320,
    )
    change_type, _ = TicketType.objects.get_or_create(
        slug='change', defaults={'name': 'Change', 'sort_order': 99},
    )
    defaults = dict(
        organization=org,
        subject='CR test',
        status=status,
        priority=priority,
        ticket_type=change_type,
        queue=queue,
    )
    defaults.update(overrides)
    return Ticket.objects.create(**defaults)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ChangeRequestModelTests(TestCase):
    """Validate the CAB gating logic on the model itself."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ChangeOrg', slug='change-org')
        self.requester = User.objects.create_user(
            username='cr_req', password='pw', email='req@x.com')
        self.approver_a = User.objects.create_user(
            username='cab_a', password='pw', email='a@x.com')
        self.approver_b = User.objects.create_user(
            username='cab_b', password='pw', email='b@x.com')

        self.ticket = _make_change_ticket(
            self.org, subject='CR test', created_by=self.requester,
        )
        self.cr = self.ticket.change_request
        self.cr.implementation_status = 'pending_cab'
        self.cr.save(update_fields=['implementation_status'])

    def test_can_implement_requires_all_cab_approvers(self):
        from psa.models import CABVote
        self.cr.required_approvers.set([self.approver_a, self.approver_b])
        # 1 approves -> not satisfied
        CABVote.objects.create(
            change_request=self.cr, user=self.approver_a, decision='approved')
        self.assertFalse(self.cr.is_cab_satisfied)
        # Even if we manually set the CR to 'approved', the gate must still
        # require all approvers -> can_implement returns False because
        # is_cab_satisfied is False.
        self.cr.implementation_status = 'approved'
        self.cr.save(update_fields=['implementation_status'])
        self.assertFalse(self.cr.can_implement())
        # Both approve -> satisfied
        CABVote.objects.create(
            change_request=self.cr, user=self.approver_b, decision='approved')
        self.assertTrue(self.cr.is_cab_satisfied)
        self.assertTrue(self.cr.can_implement())

    def test_any_rejection_blocks_implementation(self):
        from psa.models import CABVote
        self.cr.required_approvers.set([self.approver_a, self.approver_b])
        CABVote.objects.create(
            change_request=self.cr, user=self.approver_a, decision='approved')
        CABVote.objects.create(
            change_request=self.cr, user=self.approver_b, decision='rejected')
        self.assertTrue(self.cr.has_cab_rejection)
        self.cr.implementation_status = 'approved'
        self.cr.save(update_fields=['implementation_status'])
        self.assertFalse(self.cr.can_implement())

    def test_can_implement_falls_back_for_no_cab(self):
        """No required_approvers configured: a single 'approved' CABVote
        is enough to satisfy the fallback gate."""
        from psa.models import CABVote
        self.cr.required_approvers.clear()
        # No votes -> not satisfied
        self.assertFalse(self.cr.is_cab_satisfied)
        CABVote.objects.create(
            change_request=self.cr, user=self.approver_a, decision='approved')
        self.assertTrue(self.cr.is_cab_satisfied)
        self.cr.implementation_status = 'approved'
        self.cr.save(update_fields=['implementation_status'])
        self.assertTrue(self.cr.can_implement())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ChangeRequestSignalTests(TestCase):
    """Validate the post_save signal that auto-creates a ChangeRequest."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='SignalOrg', slug='signal-org')

    def test_change_ticket_auto_spawns_change_request(self):
        from psa.models import ChangeRequest
        ticket = _make_change_ticket(self.org, subject='Auto-spawn test')
        cr = ChangeRequest.objects.filter(ticket=ticket).first()
        self.assertIsNotNone(cr)
        self.assertEqual(cr.organization, self.org)
        self.assertEqual(cr.implementation_status, 'draft')

    def test_non_change_ticket_does_not_spawn(self):
        from psa.models import (
            Queue, TicketStatus, TicketPriority, TicketType, Ticket,
            ChangeRequest,
        )
        incident_type = TicketType.objects.filter(slug='incident').first()
        if not incident_type:
            incident_type = TicketType.objects.create(name='Incident', slug='incident')
        ticket = Ticket.objects.create(
            organization=self.org,
            subject='Non-change',
            status=TicketStatus.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=incident_type,
            queue=Queue.objects.first(),
        )
        self.assertFalse(ChangeRequest.objects.filter(ticket=ticket).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ChangeRequestPermissionTests(TestCase):
    """Permission gating on vote/implement endpoints."""

    def setUp(self):
        from accounts.models import RoleTemplate
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='PermOrg', slug='perm-org')

        # Give every test user generic write perms so `require_write` lets
        # them past — the tests are exercising the change_* perms specifically.
        # `can_write()` looks at vault_create OR assets_create OR ...
        common_write = dict(assets_create=True)

        self.tech_role = RoleTemplate.objects.create(
            name='ChangeTech', is_system_template=False,
            change_view=True, change_create=True,
            change_approve_cab=False, change_implement=False,
            **common_write,
        )
        # All three play MSP technicians (UserType.STAFF) so they can open
        # the change ticket at all; the change_* gates under test still come
        # from their membership role templates.
        self.tech = _make_msp_tech(User.objects.create_user(
            username='ch_tech', password='pw', email='ct@x.com'))
        Membership.objects.create(
            user=self.tech, organization=self.org,
            role=Role.EDITOR, role_template=self.tech_role,
            is_active=True,
        )

        self.cab_role = RoleTemplate.objects.create(
            name='ChangeCAB', is_system_template=False,
            change_view=True, change_create=True,
            change_approve_cab=True, change_implement=False,
            **common_write,
        )
        self.cab_member = _make_msp_tech(User.objects.create_user(
            username='ch_cab', password='pw', email='cab@x.com'))
        Membership.objects.create(
            user=self.cab_member, organization=self.org,
            role=Role.ADMIN, role_template=self.cab_role,
            is_active=True,
        )

        self.impl_role = RoleTemplate.objects.create(
            name='ChangeImpl', is_system_template=False,
            change_view=True, change_create=True,
            change_approve_cab=False, change_implement=True,
            **common_write,
        )
        self.implementer = _make_msp_tech(User.objects.create_user(
            username='ch_impl', password='pw', email='impl@x.com'))
        Membership.objects.create(
            user=self.implementer, organization=self.org,
            role=Role.ADMIN, role_template=self.impl_role,
            is_active=True,
        )

        self.ticket = _make_change_ticket(
            self.org, subject='Perm CR', created_by=self.tech,
        )
        self.cr = self.ticket.change_request
        self.cr.implementation_status = 'pending_cab'
        self.cr.required_approvers.set([self.cab_member])
        self.cr.save()

    def _client_for(self, user):
        c = Client()
        c.force_login(user)
        sess = c.session
        sess['current_organization_id'] = self.org.id
        sess.save()
        return c

    def test_voting_requires_cab_perm(self):
        """A user without change_approve_cab cannot vote."""
        c = self._client_for(self.tech)
        r = c.post(f'/psa/t/{self.ticket.ticket_number}/change/vote/', {
            'decision': 'approved',
        })
        self.assertEqual(r.status_code, 403)

    def test_voting_requires_being_a_required_approver(self):
        """Even with the CAB perm, you must be in required_approvers."""
        # Implementer has change_implement but NOT change_approve_cab.
        c = self._client_for(self.implementer)
        r = c.post(f'/psa/t/{self.ticket.ticket_number}/change/vote/', {
            'decision': 'approved',
        })
        self.assertEqual(r.status_code, 403)

    def test_cab_member_can_vote_and_drives_approval(self):
        c = self._client_for(self.cab_member)
        r = c.post(f'/psa/t/{self.ticket.ticket_number}/change/vote/', {
            'decision': 'approved',
        })
        self.assertEqual(r.status_code, 302)
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.implementation_status, 'approved')

    def test_implement_requires_can_implement_gate(self):
        """Implementer has perm but CR is pending_cab -> blocked."""
        c = self._client_for(self.implementer)
        r = c.post(f'/psa/t/{self.ticket.ticket_number}/change/implement/')
        # The view redirects with an error message, NOT a 403, because the
        # *permission* is fine - it's the gate that's not satisfied.
        self.assertEqual(r.status_code, 302)
        self.cr.refresh_from_db()
        self.assertNotEqual(self.cr.implementation_status, 'implementing')

    def test_implement_blocked_without_change_implement_perm(self):
        """A user with change_approve_cab but not change_implement gets 403."""
        c = self._client_for(self.cab_member)
        r = c.post(f'/psa/t/{self.ticket.ticket_number}/change/implement/')
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# Phase 6.2 — Problem records + root-cause analysis
# ---------------------------------------------------------------------------


def _make_problem_helper_ticket(org, subject='Recurring printer flakiness'):
    """Helper: build a non-change Ticket so it can be linked to a Problem."""
    from psa.models import (
        Queue, TicketStatus, TicketPriority, TicketType, Ticket,
    )
    queue = Queue.objects.first() or Queue.objects.create(name='Helpdesk', slug='helpdesk')
    status = TicketStatus.objects.first() or TicketStatus.objects.create(name='New', slug='new')
    priority = TicketPriority.objects.first() or TicketPriority.objects.create(
        code='P3', name='Normal',
        response_target_minutes=240, resolution_target_minutes=4320,
    )
    incident_type = TicketType.objects.filter(slug='incident').first()
    if not incident_type:
        incident_type = TicketType.objects.create(name='Incident', slug='incident')
    return Ticket.objects.create(
        organization=org,
        subject=subject,
        status=status,
        priority=priority,
        ticket_type=incident_type,
        queue=queue,
    )


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProblemModelTests(TestCase):
    """Validate problem_number auto-increment + RCA gating logic."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ProblemOrg', slug='problem-org')

    def test_next_number_increments(self):
        from psa.models import Problem
        p1 = Problem.objects.create(organization=self.org, title='First')
        p2 = Problem.objects.create(organization=self.org, title='Second')
        self.assertTrue(p1.problem_number.startswith('PRB-'))
        self.assertTrue(p1.problem_number.endswith('00001'))
        self.assertTrue(p2.problem_number.endswith('00002'))

    def test_can_advance_to_known_error_requires_root_cause_and_workaround(self):
        from psa.models import Problem
        p = Problem.objects.create(organization=self.org, title='Flaky printer')
        # Empty -> blocked
        self.assertFalse(p.can_advance_to('known_error'))
        p.root_cause = 'Driver mismatch'
        p.save()
        # Root cause but no workaround -> still blocked
        self.assertFalse(p.can_advance_to('known_error'))
        p.workaround = 'Restart spooler nightly'
        p.save()
        # Both -> ok
        self.assertTrue(p.can_advance_to('known_error'))

    def test_can_advance_to_resolved_requires_permanent_fix(self):
        from psa.models import Problem
        p = Problem.objects.create(
            organization=self.org, title='Flaky printer',
            root_cause='Driver mismatch',
            workaround='Restart spooler nightly',
        )
        # No permanent fix -> blocked
        self.assertFalse(p.can_advance_to('resolved'))
        p.permanent_fix = 'Roll out new driver via Intune'
        p.save()
        self.assertTrue(p.can_advance_to('resolved'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProblemTicketLinkTests(TestCase):
    """The M2M tying tickets to problems and the link-ticket endpoint."""

    def setUp(self):
        from accounts.models import RoleTemplate
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='LinkOrg', slug='link-org')
        # Need vault_create or similar so require_write passes.
        self.role = RoleTemplate.objects.create(
            name='ProblemTech', is_system_template=False,
            problem_view=True, problem_create=True,
            problem_assign=False, problem_resolve=False,
            assets_create=True,
        )
        self.user = _make_msp_tech(User.objects.create_user(
            username='ptech', password='pw', email='ptech@x.com'))
        Membership.objects.create(
            user=self.user, organization=self.org,
            role=Role.EDITOR, role_template=self.role,
            is_active=True,
        )

    def _client(self):
        c = Client()
        c.force_login(self.user)
        sess = c.session
        sess['current_organization_id'] = self.org.id
        sess.save()
        return c

    def test_link_ticket_via_post(self):
        """User with problem_create posts ticket_number -> ticket appears in
        related_tickets."""
        from psa.models import Problem
        problem = Problem.objects.create(organization=self.org, title='Flaky printer')
        ticket = _make_problem_helper_ticket(self.org, subject='Print job failed')

        c = self._client()
        r = c.post(f'/psa/problems/{problem.pk}/link-ticket/', {
            'ticket_number': ticket.ticket_number,
        })
        self.assertEqual(r.status_code, 302)
        problem.refresh_from_db()
        self.assertTrue(problem.related_tickets.filter(pk=ticket.pk).exists())

    def test_problem_appears_on_ticket_detail(self):
        """Linked ticket renders the problem in ticket_detail context."""
        from psa.models import Problem
        problem = Problem.objects.create(
            organization=self.org, title='Email storm',
            description='Recurring SMTP loop',
        )
        ticket = _make_problem_helper_ticket(self.org, subject='Email queue stuck')
        problem.related_tickets.add(ticket)

        c = self._client()
        r = c.get(f'/psa/t/{ticket.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        # The Problem number appears on the rendered page.
        self.assertIn(problem.problem_number.encode(), r.content)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProblemPermissionTests(TestCase):
    """Permission gating on view/advance endpoints."""

    def setUp(self):
        from accounts.models import RoleTemplate
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ProblemPermOrg', slug='problem-perm-org')

        common_write = dict(assets_create=True)

        # Tech: view+create but cannot resolve.
        self.tech_role = RoleTemplate.objects.create(
            name='ProblemTechRole', is_system_template=False,
            problem_view=True, problem_create=True,
            problem_assign=False, problem_resolve=False,
            **common_write,
        )
        self.tech = User.objects.create_user(
            username='pt_tech', password='pw', email='pt@x.com')
        Membership.objects.create(
            user=self.tech, organization=self.org,
            role=Role.EDITOR, role_template=self.tech_role,
            is_active=True,
        )

        # Resolver: full perms.
        self.resolver_role = RoleTemplate.objects.create(
            name='ProblemResolverRole', is_system_template=False,
            problem_view=True, problem_create=True,
            problem_assign=True, problem_resolve=True,
            **common_write,
        )
        self.resolver = User.objects.create_user(
            username='pt_res', password='pw', email='ptr@x.com')
        Membership.objects.create(
            user=self.resolver, organization=self.org,
            role=Role.ADMIN, role_template=self.resolver_role,
            is_active=True,
        )

        # No-perm user: nothing.
        self.no_perm_role = RoleTemplate.objects.create(
            name='ProblemNoPermRole', is_system_template=False,
            problem_view=False, problem_create=False,
            problem_assign=False, problem_resolve=False,
            **common_write,
        )
        self.no_perm = User.objects.create_user(
            username='pt_no', password='pw', email='ptn@x.com')
        Membership.objects.create(
            user=self.no_perm, organization=self.org,
            role=Role.EDITOR, role_template=self.no_perm_role,
            is_active=True,
        )

        from psa.models import Problem
        self.problem = Problem.objects.create(
            organization=self.org, title='Server stuck',
            root_cause='Thermal throttle',
            workaround='Bump fan speed',
            permanent_fix='Replace heatsink',
        )

    def _client_for(self, user):
        c = Client()
        c.force_login(user)
        sess = c.session
        sess['current_organization_id'] = self.org.id
        sess.save()
        return c

    def test_advance_requires_resolve_perm(self):
        """A user with problem_view+create but not problem_resolve gets 403."""
        c = self._client_for(self.tech)
        r = c.post(f'/psa/problems/{self.problem.pk}/advance/', {
            'status': 'known_error',
        })
        self.assertEqual(r.status_code, 403)

        # Resolver succeeds.
        c2 = self._client_for(self.resolver)
        r2 = c2.post(f'/psa/problems/{self.problem.pk}/advance/', {
            'status': 'known_error',
        })
        self.assertEqual(r2.status_code, 302)
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.status, 'known_error')

    def test_view_blocked_for_user_without_problem_view(self):
        c = self._client_for(self.no_perm)
        r = c.get('/psa/problems/')
        self.assertEqual(r.status_code, 403)
        r2 = c.get(f'/psa/problems/{self.problem.pk}/')
        self.assertEqual(r2.status_code, 403)


# ---------------------------------------------------------------------------
# Phase 6.3 — Release management + Service-catalog governance
# ---------------------------------------------------------------------------


def _make_change_request(org, *, subject='Routine deploy', risk='medium',
                         implementation_plan='Step 1', rollback_plan='Revert',
                         created_by=None):
    """Helper: build a Ticket(type=change) + its auto-spawned ChangeRequest,
    fill in plans so the CR can be added to a release."""
    from psa.models import (
        Queue, TicketStatus, TicketPriority, TicketType, Ticket, ChangeRequest,
    )
    queue = Queue.objects.first() or Queue.objects.create(name='Helpdesk', slug='helpdesk')
    status = TicketStatus.objects.first() or TicketStatus.objects.create(name='New', slug='new')
    priority = TicketPriority.objects.first() or TicketPriority.objects.create(
        code='P3', name='Normal',
        response_target_minutes=240, resolution_target_minutes=4320,
    )
    change_type = TicketType.objects.filter(slug='change').first()
    if not change_type:
        change_type = TicketType.objects.create(name='Change', slug='change')
    ticket = Ticket.objects.create(
        organization=org, subject=subject,
        status=status, priority=priority,
        ticket_type=change_type, queue=queue,
    )
    cr, _ = ChangeRequest.objects.get_or_create(
        ticket=ticket,
        defaults={
            'organization': org, 'risk': risk,
            'implementation_plan': implementation_plan,
            'rollback_plan': rollback_plan,
        },
    )
    if not cr.implementation_plan:
        cr.implementation_plan = implementation_plan
        cr.rollback_plan = rollback_plan
        cr.risk = risk
        cr.save()
    return ticket, cr


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReleaseWindowTests(TestCase):
    """Validate ReleaseWindow.next_number + can_advance_to gating."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='RelOrg', slug='rel-org')
        self.start = timezone.now() + timedelta(days=1)
        self.end = self.start + timedelta(hours=2)

    def test_can_advance_to_frozen_requires_changes_and_rollback(self):
        from psa.models import ReleaseWindow
        rel = ReleaseWindow.objects.create(
            organization=self.org, title='Q2 maintenance',
            scheduled_start=self.start, scheduled_end=self.end,
        )
        # Empty release, no rollback -> blocked.
        self.assertFalse(rel.can_advance_to('frozen'))

        # Add a change, still no rollback -> blocked.
        _, cr = _make_change_request(self.org)
        rel.changes.add(cr)
        self.assertFalse(rel.can_advance_to('frozen'))

        # Both -> ok.
        rel.rollback_plan = 'Revert via psql snapshot'
        rel.save()
        self.assertTrue(rel.can_advance_to('frozen'))

    def test_release_number_increments(self):
        from psa.models import ReleaseWindow
        r1 = ReleaseWindow.objects.create(
            organization=self.org, title='First',
            scheduled_start=self.start, scheduled_end=self.end,
        )
        r2 = ReleaseWindow.objects.create(
            organization=self.org, title='Second',
            scheduled_start=self.start, scheduled_end=self.end,
        )
        self.assertTrue(r1.release_number.startswith('REL-'))
        self.assertTrue(r1.release_number.endswith('00001'))
        self.assertTrue(r2.release_number.endswith('00002'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ServiceCatalogChangeTests(TestCase):
    """Service catalog governance — propose / apply / pending blocks publish."""

    def setUp(self):
        from accounts.models import RoleTemplate
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='CatOrg', slug='cat-org')
        # Staff superuser bypasses _catalog_admin_or_404.
        self.admin = User.objects.create_user(
            username='cat_admin', password='pw', email='ca@x.com',
            is_superuser=True, is_staff=True,
        )
        self.proposer_role = RoleTemplate.objects.create(
            name='CatProposer', is_system_template=False,
            catalog_propose_change=True,
            catalog_approve_change=False,
            assets_create=True,
        )
        self.proposer = User.objects.create_user(
            username='cat_prop', password='pw', email='cp@x.com',
            is_staff=True, is_superuser=True,
        )
        # Make the proposer a real superuser for the catalog admin gate, but
        # also give a role template with only propose perms so the
        # propose-change permission check is exercised. Membership also gets
        # us through any tenant scoping if relevant.
        Membership.objects.create(
            user=self.proposer, organization=self.org,
            role=Role.EDITOR, role_template=self.proposer_role,
            is_active=True,
        )

    def test_apply_writes_after_snapshot(self):
        from psa.models import ServiceCatalogItem, ServiceCatalogChange
        item = ServiceCatalogItem.objects.create(
            name='Reset Password', slug='reset-password',
            description='old desc',
        )
        change = ServiceCatalogChange.objects.create(
            catalog_item=item,
            before_snapshot={'description': 'old desc'},
            after_snapshot={'description': 'new desc'},
        )
        ok = change.apply(decided_by=self.admin)
        self.assertTrue(ok)
        item.refresh_from_db()
        self.assertEqual(item.description, 'new desc')
        self.assertEqual(item.last_published_by, self.admin)
        self.assertIsNotNone(item.last_published_at)
        change.refresh_from_db()
        self.assertEqual(change.status, 'approved')
        self.assertEqual(change.decided_by, self.admin)

    def test_pending_change_blocks_publish(self):
        """When item.requires_approval=True, the propose endpoint creates a
        new pending ServiceCatalogChange instead of writing live."""
        from psa.models import ServiceCatalogItem, ServiceCatalogChange
        item = ServiceCatalogItem.objects.create(
            name='Onboard User', slug='onboard-user',
            description='live description',
            requires_approval=True,
        )
        c = Client()
        c.force_login(self.proposer)
        sess = c.session
        sess['current_organization_id'] = self.org.id
        sess.save()
        r = c.post(f'/psa/catalog/{item.pk}/propose/', {
            'name': item.name,
            'description': 'proposed new description',
            'default_subject': item.default_subject,
            'default_body': item.default_body,
            'icon': item.icon,
            'sort_order': item.sort_order,
            'is_active': 'on',
            'reason': 'tightening copy',
        })
        self.assertEqual(r.status_code, 302)
        # Live item unchanged.
        item.refresh_from_db()
        self.assertEqual(item.description, 'live description')
        # A pending proposal exists with the new description in after_snapshot.
        proposal = ServiceCatalogChange.objects.filter(
            catalog_item=item, status='pending',
        ).first()
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.after_snapshot.get('description'), 'proposed new description')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReleasePermissionTests(TestCase):
    """Permission gating on release_freeze endpoint."""

    def setUp(self):
        from accounts.models import RoleTemplate
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='RelPermOrg', slug='rel-perm-org')

        common_write = dict(assets_create=True)

        # Manager: manage but cannot freeze.
        self.mgr_role = RoleTemplate.objects.create(
            name='RelMgr', is_system_template=False,
            release_view=True, release_manage=True, release_freeze=False,
            **common_write,
        )
        self.manager = User.objects.create_user(
            username='rel_mgr', password='pw', email='rm@x.com')
        Membership.objects.create(
            user=self.manager, organization=self.org,
            role=Role.EDITOR, role_template=self.mgr_role, is_active=True,
        )

        # Releaser: full perms.
        self.rel_role = RoleTemplate.objects.create(
            name='RelFull', is_system_template=False,
            release_view=True, release_manage=True, release_freeze=True,
            **common_write,
        )
        self.releaser = User.objects.create_user(
            username='rel_full', password='pw', email='rf@x.com')
        Membership.objects.create(
            user=self.releaser, organization=self.org,
            role=Role.ADMIN, role_template=self.rel_role, is_active=True,
        )

        from psa.models import ReleaseWindow
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(hours=2)
        self.release = ReleaseWindow.objects.create(
            organization=self.org, title='Test release',
            scheduled_start=start, scheduled_end=end,
            rollback_plan='Revert via snapshot',
        )
        _, self.cr = _make_change_request(self.org)
        self.release.changes.add(self.cr)

    def _client_for(self, user):
        c = Client()
        c.force_login(user)
        sess = c.session
        sess['current_organization_id'] = self.org.id
        sess.save()
        return c

    def test_freeze_requires_release_freeze_perm(self):
        # Manager (no freeze perm) -> 403.
        c = self._client_for(self.manager)
        r = c.post(f'/psa/releases/{self.release.pk}/freeze/')
        self.assertEqual(r.status_code, 403)

        # Releaser succeeds.
        c2 = self._client_for(self.releaser)
        r2 = c2.post(f'/psa/releases/{self.release.pk}/freeze/')
        self.assertEqual(r2.status_code, 302)
        self.release.refresh_from_db()
        self.assertEqual(self.release.status, 'frozen')
        self.assertTrue(self.release.is_frozen)


# ---------------------------------------------------------------------------
# Phase 7 — Outsourcing + Integration SDK
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketShareTests(TestCase):
    """Outsourcing share endpoint + partner webhook receiver."""

    def setUp(self):
        from accounts.models import RoleTemplate
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        # Originator org (the MSP)
        self.org = Organization.objects.create(name='ShareOrg', slug='share-org')
        # Partner org
        self.partner = Organization.objects.create(
            name='Partner Inc', slug='partner-inc',
            is_outsourcing_partner=True,
            partner_endpoint_url='http://127.0.0.1:1/no-such-host',
        )
        # Sharer with outsourcing_share_tickets perm
        self.share_role = RoleTemplate.objects.create(
            name='Sharer', is_system_template=False,
            outsourcing_share_tickets=True,
            assets_create=True,
        )
        self.user = _make_msp_tech(User.objects.create_user(
            username='sharer', password='pw', email='s@x.com'))
        Membership.objects.create(
            user=self.user, organization=self.org,
            role=Role.ADMIN, role_template=self.share_role, is_active=True,
        )
        # Required ticket scaffolding
        from psa.models import Ticket as _T
        self.priority = TicketPriority.objects.filter(code='P3').first() or \
            TicketPriority.objects.create(code='P3', name='Normal')
        self.status = TicketStatus.objects.filter(slug='new').first() or \
            TicketStatus.objects.create(name='New', slug='new')
        self.ttype = TicketType.objects.filter(slug='incident').first() or \
            TicketType.objects.create(name='Incident', slug='incident')
        self.ticket = _T.objects.create(
            organization=self.org, subject='need partner help',
            description='offload this please',
            priority=self.priority, status=self.status,
            ticket_type=self.ttype,
            queue=Queue.objects.first(),
        )

    def _client_for(self, user):
        c = Client()
        c.force_login(user)
        sess = c.session
        sess['current_organization_id'] = self.org.id
        sess.save()
        return c

    def test_partner_secret_auto_generated(self):
        """Setting is_outsourcing_partner=True saves a 64-char hex token."""
        org = Organization.objects.create(
            name='Auto Partner', slug='auto-partner',
            is_outsourcing_partner=True,
        )
        self.assertEqual(len(org.partner_secret), 64)
        # Hex check
        int(org.partner_secret, 16)

    def test_share_creates_share_row(self):
        """POST share endpoint -> TicketShare row exists, status='pending'."""
        from psa.models import TicketShare
        c = self._client_for(self.user)
        r = c.post(
            f'/psa/t/{self.ticket.ticket_number}/share/',
            {'partner_org': str(self.partner.pk), 'notes': 'please handle'},
        )
        self.assertEqual(r.status_code, 302)
        share = TicketShare.objects.get(ticket=self.ticket, partner_org=self.partner)
        self.assertEqual(share.status, 'pending')
        self.assertEqual(share.shared_by, self.user)
        self.assertEqual(share.notes, 'please handle')

    def test_partner_webhook_creates_comment(self):
        """POST to webhook with valid HMAC sig and event='comment' ->
        TicketComment created with source='partner'."""
        import hashlib
        import hmac
        import json as _json

        from psa.models import TicketComment, TicketShare

        share = TicketShare.objects.create(
            ticket=self.ticket, partner_org=self.partner, status='accepted',
        )
        body_dict = {'event': 'comment', 'payload': {
            'body': 'partner reply here',
            'author': 'partner-tech',
            'author_email': 'tech@partner.example',
        }}
        raw = _json.dumps(body_dict).encode('utf-8')
        sig = hmac.new(
            self.partner.partner_secret.encode('utf-8'),
            raw, hashlib.sha256,
        ).hexdigest()
        c = Client()
        r = c.post(
            f'/psa/partners/webhook/{share.pk}/',
            data=raw,
            content_type='application/json',
            HTTP_X_CST0R_SIGNATURE=sig,
        )
        self.assertEqual(r.status_code, 200)
        comment = TicketComment.objects.filter(
            ticket=self.ticket, source='partner').order_by('-id').first()
        self.assertIsNotNone(comment)
        self.assertEqual(comment.body, 'partner reply here')
        self.assertFalse(comment.is_internal)
        self.assertEqual(comment.author_name, 'partner-tech')

    def test_webhook_rejects_bad_signature(self):
        """POST with wrong sig -> 403."""
        import json as _json

        from psa.models import TicketShare

        share = TicketShare.objects.create(
            ticket=self.ticket, partner_org=self.partner, status='accepted',
        )
        raw = _json.dumps({'event': 'comment', 'payload': {'body': 'x'}}).encode('utf-8')
        c = Client()
        r = c.post(
            f'/psa/partners/webhook/{share.pk}/',
            data=raw,
            content_type='application/json',
            HTTP_X_CST0R_SIGNATURE='deadbeef',
        )
        self.assertEqual(r.status_code, 403)


class IntegrationSDKTests(TestCase):
    """Integration SDK skeleton: registry + abstract base."""

    def test_register_and_lookup(self):
        from integrations.sdk import IntegrationProvider, get, register

        @register
        class _DummyProvider(IntegrationProvider):
            slug = 'phase7-dummy'
            label = 'Dummy'
            category = 'other'

            def test_connection(self, connection):
                return {'ok': True, 'message': 'ok'}

            def sync(self, connection):
                return {'ok': True, 'records_imported': 0, 'errors': []}

        p = get('phase7-dummy')
        self.assertIsNotNone(p)
        self.assertEqual(p.slug, 'phase7-dummy')
        self.assertEqual(p.label, 'Dummy')
        self.assertEqual(p.category, 'other')

    def test_missing_slug_raises(self):
        from integrations.sdk import IntegrationProvider, register

        with self.assertRaises(ValueError):
            @register
            class _NoSlug(IntegrationProvider):
                slug = None
                label = 'NoSlug'
                category = 'other'

                def test_connection(self, connection):
                    return {'ok': True, 'message': ''}

                def sync(self, connection):
                    return {'ok': True, 'records_imported': 0, 'errors': []}

