"""
Phase 46 (v3.17.533) — job kit: what the tech has to take.

Tools, inventory items and free-text items attach to a ticket so whoever
attends knows what to load before leaving.
"""
from __future__ import annotations

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Organization
from inventory.models import InventoryCategory, InventoryItem, InventoryLocation, Tool
from core.models import SystemSetting
from psa.models import (
    Queue, Ticket, TicketKitItem, TicketPriority, TicketStatus, TicketType,
)
from psa.tests._base import _enable_psa_for, _setup_seed

_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class _KitCase(TestCase):

    def setUp(self):
        # A Ticket needs queue / priority / type / status, all PROTECT FKs that
        # the seed command provides. setUp rather than setUpTestData because the
        # seed is a management command, not fixture data.
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()

        self.org = Organization.objects.create(name='KitCo', slug='kit-co')
        self.other_org = Organization.objects.create(name='OtherCo', slug='other-co')
        self.admin = User.objects.create_superuser('kitadmin', 'k@x.com', 'pw')
        _enable_psa_for(self.org)

        self.location = InventoryLocation.objects.create(
            organization=self.org, name='Shelf B')
        self.tool = Tool.objects.create(
            organization=self.org, name='Cable tester', code='TL-014',
            home_location=self.location)
        self.item = InventoryItem.objects.create(
            organization=self.org, name='CAT6 patch 3ft', quantity=40)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Replace switch',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )


class ToolModelTests(_KitCase):

    def test_a_used_code_is_unique_per_tenant(self):
        """Two tools answering to TL-014 makes the asset tag useless."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tool.objects.create(
                organization=self.org, name='Second tester', code='TL-014')

    def test_a_blank_code_is_not_subject_to_the_constraint(self):
        """Plenty of shops don't tag anything; that must not block a second tool."""
        Tool.objects.create(organization=self.org, name='Drill')
        Tool.objects.create(organization=self.org, name='Ladder')
        self.assertEqual(Tool.objects.filter(code='').count(), 2)

    def test_the_same_code_may_exist_in_another_tenant(self):
        Tool.objects.create(
            organization=self.other_org, name='Their tester', code='TL-014')
        self.assertEqual(Tool.objects.filter(code='TL-014').count(), 2)

    def test_home_prefers_the_vehicle_over_the_shelf(self):
        """A tech asks where a tool is; the van it rides in is the better answer."""
        from vehicles.models import ServiceVehicle
        van = ServiceVehicle.objects.create(
            name='Van 3', make='Ford', model='Transit', year=2022,
            license_plate='VAN3', status='active')
        self.tool.assigned_vehicle = van
        self.tool.save()
        self.assertIn('Van 3', self.tool.home)

    def test_retired_and_broken_tools_are_not_available(self):
        self.tool.is_active = False
        self.assertFalse(self.tool.is_available)
        self.tool.is_active = True
        self.tool.condition = 'out_of_service'
        self.assertFalse(self.tool.is_available)


class KitItemModelTests(_KitCase):

    def test_a_tool_line_records_its_label_for_when_the_tool_goes(self):
        """The FK is SET_NULL. A packing list that empties itself because
        somebody retired a tool is worse than a stale label."""
        line = TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_TOOL, tool=self.tool)
        self.assertIn('Cable tester', line.description)

        self.tool.delete()
        line.refresh_from_db()
        self.assertIsNone(line.tool_id)
        self.assertIn('Cable tester', line.label)

    def test_kind_and_foreign_keys_must_agree(self):
        line = TicketKitItem(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_TOOL, inventory_item=self.item)
        with self.assertRaises(ValidationError):
            line.full_clean(exclude=['organization', 'ticket'])

    def test_an_other_line_needs_a_description(self):
        line = TicketKitItem(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_OTHER)
        with self.assertRaises(ValidationError):
            line.full_clean(exclude=['organization', 'ticket'])

    def test_an_other_line_must_not_reference_a_row(self):
        line = TicketKitItem(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_OTHER, description='Loaner laptop',
            tool=self.tool)
        with self.assertRaises(ValidationError):
            line.full_clean(exclude=['organization', 'ticket'])

    def test_the_same_tool_cannot_be_listed_twice(self):
        """That is a slip, not a request for two lines — quantity says two."""
        TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_TOOL, tool=self.tool)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TicketKitItem.objects.create(
                organization=self.org, ticket=self.ticket,
                kind=TicketKitItem.KIND_TOOL, tool=self.tool)

    def test_shortfall_flags_more_wanted_than_stocked(self):
        """Telling a tech to take eight of something there are three of is the
        failure this list exists to prevent."""
        self.item.quantity = 3
        self.item.save()
        line = TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_INVENTORY, inventory_item=self.item,
            quantity=8)
        self.assertEqual(line.stock_shortfall, 5)

    def test_no_shortfall_when_stock_covers_it(self):
        line = TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_INVENTORY, inventory_item=self.item,
            quantity=8)
        self.assertEqual(line.stock_shortfall, 0)

    def test_tools_never_report_a_shortfall(self):
        line = TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_TOOL, tool=self.tool, quantity=5)
        self.assertEqual(line.stock_shortfall, 0)

    def test_where_points_at_the_stored_location(self):
        line = TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_TOOL, tool=self.tool)
        self.assertEqual(line.where, 'Shelf B')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class KitViewTests(_KitCase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        session = self.client.session
        session['2fa_prompted'] = True
        session['current_organization_id'] = self.org.id
        session.save()

    def _add(self, **data):
        return self.client.post(
            reverse('psa:ticket_kit_add', args=[self.ticket.ticket_number]),
            data, follow=True)

    def test_adding_a_tool_line(self):
        self._add(kind='tool', tool=self.tool.pk, quantity=1)
        self.assertEqual(self.ticket.kit_items.count(), 1)

    def test_adding_an_other_line_without_a_description_is_rejected(self):
        r = self._add(kind='other', description='  ', quantity=1)
        self.assertEqual(self.ticket.kit_items.count(), 0)
        self.assertContains(r, 'Describe the item')

    def test_a_tool_from_another_tenant_cannot_be_attached(self):
        """The picker is scoped, but the id is a form field like any other."""
        theirs = Tool.objects.create(
            organization=self.other_org, name='Their tester')
        r = self._add(kind='tool', tool=theirs.pk, quantity=1)
        self.assertEqual(self.ticket.kit_items.count(), 0)
        self.assertContains(r, 'A tool line needs a tool')

    def test_adding_a_duplicate_is_reported_not_crashed(self):
        self._add(kind='tool', tool=self.tool.pk, quantity=1)
        r = self._add(kind='tool', tool=self.tool.pk, quantity=1)
        self.assertEqual(self.ticket.kit_items.count(), 1)
        self.assertContains(r, 'already on the list')

    def test_toggling_packed_records_who_and_when(self):
        line = TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_TOOL, tool=self.tool)
        self.client.post(reverse('psa:ticket_kit_toggle_packed',
                                 args=[self.ticket.ticket_number, line.pk]))
        line.refresh_from_db()
        self.assertTrue(line.packed)
        self.assertEqual(line.packed_by, self.admin)
        self.assertIsNotNone(line.packed_at)

        self.client.post(reverse('psa:ticket_kit_toggle_packed',
                                 args=[self.ticket.ticket_number, line.pk]))
        line.refresh_from_db()
        self.assertFalse(line.packed)
        self.assertIsNone(line.packed_at)

    def test_removing_a_line(self):
        line = TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_TOOL, tool=self.tool)
        self.client.post(reverse('psa:ticket_kit_remove',
                                 args=[self.ticket.ticket_number, line.pk]))
        self.assertEqual(self.ticket.kit_items.count(), 0)

    def test_kit_endpoints_reject_get(self):
        r = self.client.get(
            reverse('psa:ticket_kit_add', args=[self.ticket.ticket_number]))
        self.assertEqual(r.status_code, 405)

    def test_the_kit_renders_on_the_ticket_page(self):
        TicketKitItem.objects.create(
            organization=self.org, ticket=self.ticket,
            kind=TicketKitItem.KIND_OTHER, description='Loaner laptop')
        r = self.client.get(
            reverse('psa:ticket_detail', args=[self.ticket.ticket_number]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Kit to take')
        self.assertContains(r, 'Loaner laptop')
