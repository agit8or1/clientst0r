"""Phase 13 — serial lifecycle tracking."""
from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from assets import serial_lifecycle
from assets.models import Asset, RMAReturn, SerialEvent, Vendor
from core.models import Organization, SystemSetting

# Not imported from assets.tests: importing that module here would make the
# test runner collect its test classes a second time.
TEST_MIDDLEWARE = [m for m in __import__('django.conf').conf.settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


def _login_in_org(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


def _types(qs):
    return list(qs.order_by('occurred_at', 'id').values_list('event_type', flat=True))


class SerialSignalTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='SerialCo', slug='serial-co')
        self.other = Organization.objects.create(name='OtherSerial', slug='other-serial')
        self.vendor = Vendor.objects.create(name='Vend', slug='vend')

    def test_normalize(self):
        self.assertEqual(serial_lifecycle.normalize(' ab 12-c\n'), 'AB12-C')
        self.assertEqual(serial_lifecycle.normalize(None), '')

    def test_asset_create_with_serial_records_assigned(self):
        a = Asset.objects.create(organization=self.org, name='Laptop', serial_number='SN-1')
        ev = SerialEvent.objects.get(asset=a)
        self.assertEqual((ev.event_type, ev.serial_key, ev.organization), ('assigned', 'SN-1', self.org))
        self.assertEqual(ev.asset_name, 'Laptop')

    def test_asset_without_serial_records_nothing(self):
        Asset.objects.create(organization=self.org, name='No serial')
        self.assertFalse(SerialEvent.objects.exists())

    def test_serial_change_records_unassigned_and_assigned(self):
        a = Asset.objects.create(organization=self.org, name='Laptop', serial_number='OLD')
        a.serial_number = 'NEW'
        a.save()
        self.assertEqual(_types(SerialEvent.objects.filter(serial_key='OLD')), ['assigned', 'unassigned'])
        self.assertEqual(_types(SerialEvent.objects.filter(serial_key='NEW')), ['assigned'])

    def test_unrelated_save_records_nothing(self):
        a = Asset.objects.create(organization=self.org, name='Laptop', serial_number='SN-1')
        a.name = 'Renamed'
        a.save()
        self.assertEqual(SerialEvent.objects.count(), 1)

    def test_move_to_other_customer_leaves_event_on_both_sides(self):
        a = Asset.objects.create(organization=self.org, name='Laptop', serial_number='SN-9')
        a.organization = self.other
        a.save()
        self.assertEqual(_types(SerialEvent.objects.filter(organization=self.org)), ['assigned', 'moved_out'])
        self.assertEqual(_types(SerialEvent.objects.filter(organization=self.other)), ['moved_in'])

    def test_rma_lifecycle_and_replacement(self):
        a = Asset.objects.create(organization=self.org, name='Switch', serial_number='SW-1')
        rma = RMAReturn.objects.create(organization=self.org, vendor=self.vendor, asset=a,
                                       reason='DOA', rma_number='R-1')
        for status in ('sent', 'received_by_vendor'):
            rma.transition(status)
            rma.save()
        rma.transition('replaced')
        rma.replacement_serial = 'SW-2'
        rma.save()
        self.assertEqual(_types(SerialEvent.objects.filter(serial_key='SW-1')),
                         ['assigned', 'rma_opened', 'rma_sent', 'rma_received_by_vendor', 'rma_replaced'])
        repl = SerialEvent.objects.get(serial_key='SW-2')
        self.assertEqual(repl.event_type, 'replacement_received')
        self.assertEqual(repl.rma, rma)
        self.assertIn('SW-1', repl.notes)

    def test_rma_without_any_serial_records_nothing(self):
        RMAReturn.objects.create(organization=self.org, vendor=self.vendor, reason='x')
        self.assertFalse(SerialEvent.objects.exists())

    def test_history_for_asset_is_customer_scoped(self):
        a = Asset.objects.create(organization=self.org, name='Mine', serial_number='DUP-1')
        Asset.objects.create(organization=self.other, name='Theirs', serial_number='DUP-1')
        hist = list(serial_lifecycle.history_for_asset(a))
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0].organization, self.org)

    def test_backfill_command_is_idempotent(self):
        a = Asset.objects.create(organization=self.org, name='Old', serial_number='LEGACY')
        RMAReturn.objects.create(organization=self.org, vendor=self.vendor, serial_number='LEGACY-RMA',
                                 reason='x', status='sent')
        SerialEvent.objects.all().delete()  # as if recorded before serial tracking
        out = StringIO()
        call_command('assets_backfill_serial_history', stdout=out)
        self.assertIn('1 assigned', out.getvalue())
        self.assertEqual(_types(SerialEvent.objects.filter(serial_key='LEGACY')), ['assigned'])
        self.assertEqual(_types(SerialEvent.objects.filter(serial_key='LEGACY-RMA')), ['rma_opened', 'rma_sent'])
        call_command('assets_backfill_serial_history', stdout=StringIO())
        self.assertEqual(SerialEvent.objects.count(), 3)
        self.assertTrue(SerialEvent.objects.filter(asset=a).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SerialViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='SerialViewCo', slug='serial-view-co')
        self.other = Organization.objects.create(name='OtherView', slug='other-view')
        self.user = User.objects.create_user('serial_user', email='s@s.com', password='pw')
        Membership.objects.create(user=self.user, organization=self.org, role=Role.OWNER, is_active=True)
        self.asset = Asset.objects.create(organization=self.org, name='Edge FW', serial_number='FGT-123')
        self.foreign = Asset.objects.create(organization=self.other, name='Foreign box', serial_number='FGT-999')
        self.client = Client()
        _login_in_org(self.client, self.user, self.org)

    def test_asset_page_shows_history_tab(self):
        resp = self.client.get(f'/assets/{self.asset.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Serial history')
        self.assertContains(resp, 'Assigned to asset')

    def test_search_finds_own_serial_not_other_customers(self):
        resp = self.client.get('/assets/serials/', {'q': 'fgt'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'FGT-123')
        self.assertNotContains(resp, 'FGT-999')
        self.assertNotContains(resp, 'Foreign box')

    def test_search_without_query_is_empty(self):
        resp = self.client.get('/assets/serials/')
        self.assertEqual(resp.status_code, 200)

    def test_record_retired_and_disposed(self):
        url = f'/assets/{self.asset.pk}/serial-events/add/'
        resp = self.client.post(url, {'event_type': 'retired', 'notes': 'End of life'})
        self.assertEqual(resp.status_code, 302)
        resp = self.client.post(url, {'event_type': 'disposed', 'occurred_on': '2026-01-15',
                                      'notes': 'Certificate 42'})
        self.assertEqual(resp.status_code, 302)
        evs = SerialEvent.objects.filter(asset=self.asset).order_by('id')
        self.assertEqual([e.event_type for e in evs], ['assigned', 'retired', 'disposed'])
        self.assertEqual(evs.last().actor, self.user)
        self.assertEqual(evs.last().occurred_at.date().isoformat(), '2026-01-15')
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(object_type='asset', object_id=self.asset.pk,
                                                description__contains='Disposed').exists())

    def test_record_rejects_automatic_event_types_and_future_dates(self):
        url = f'/assets/{self.asset.pk}/serial-events/add/'
        self.client.post(url, {'event_type': 'received'})
        self.client.post(url, {'event_type': 'retired', 'occurred_on': '2999-01-01'})
        self.client.post(url, {'event_type': 'note', 'notes': ''})
        self.assertEqual(SerialEvent.objects.filter(asset=self.asset).count(), 1)

    def test_record_on_other_customers_asset_is_404(self):
        resp = self.client.post(f'/assets/{self.foreign.pk}/serial-events/add/', {'event_type': 'retired'})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(SerialEvent.objects.filter(asset=self.foreign, event_type='retired').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class POReceiveSerialTests(TestCase):
    def setUp(self):
        from accounts.models import RoleTemplate
        from psa.models import PurchaseOrder, PurchaseOrderLineItem
        from psa.tests._base import _setup_seed
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='RecvSerialCo', slug='recv-serial-co')
        self.other = Organization.objects.create(name='RecvOther', slug='recv-other')
        role = RoleTemplate.objects.create(name='SerialReceiver', is_system_template=False,
                                           procurement_view=True, procurement_create_po=True)
        # Procurement receiving is MSP-only: an MSP technician.
        from psa.tests._base import _make_msp_tech
        self.user = _make_msp_tech(User.objects.create_user(username='serial_receiver', password='pw', email='sr@x.com'))
        Membership.objects.create(user=self.user, organization=self.org, role=Role.ADMIN,
                                  role_template=role, is_active=True)
        self.po = PurchaseOrder.objects.create(organization=self.org, vendor_name='ACME', title='T',
                                               status='sent')
        self.line = PurchaseOrderLineItem.objects.create(po=self.po, description='Laptop', sku='L1',
                                                         quantity=Decimal('3'), unit_price=Decimal('5'))
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session.save()

    def test_receive_records_received_then_assigned(self):
        # Another customer already has this serial: it is not a duplicate here.
        Asset.objects.create(organization=self.other, name='Elsewhere', serial_number='LT-2')
        resp = self.client.post(f'/psa/purchase-orders/{self.po.pk}/receive/', {
            f'qty_line_{self.line.pk}': '2', f'serials_line_{self.line.pk}': 'LT-1, LT-2'})
        self.assertEqual(resp.status_code, 302)
        for sn in ('LT-1', 'LT-2'):
            evs = SerialEvent.objects.filter(organization=self.org, serial_key=sn).order_by('id')
            self.assertEqual([e.event_type for e in evs], ['received', 'assigned'])
            self.assertEqual(evs[0].purchase_order, self.po)
            self.assertIsNotNone(evs[0].receipt_line)
            self.assertEqual(evs[0].actor, self.user)
            self.assertEqual(evs[1].actor, self.user)
        self.assertTrue(Asset.objects.filter(organization=self.org, serial_number='LT-2').exists())
