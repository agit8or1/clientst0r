"""seed_module_samples --only operations: seeds every operations model once,
is idempotent, stays inert (no alerts, monitoring or active schedules), and
the seeded list pages render."""
from io import StringIO

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.demo_samples import CUSTOMER_SLUGS, MSP_SLUG
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE

SEEDED = [
    'inventory.InventoryCategory', 'inventory.InventoryLocation', 'inventory.InventoryItem',
    'inventory.InventoryTransaction', 'inventory.Tool',
    'scheduling.ScheduledTask', 'scheduling.TaskAssignment', 'scheduling.TaskComment',
    'scheduling.SchedulerWallboard',
    'resourcing.UserSkill', 'resourcing.UserCertification', 'resourcing.WorkingHours',
    'resourcing.Holiday', 'resourcing.LeaveRequest', 'resourcing.TechCostRate',
    'vehicles.ServiceVehicle', 'vehicles.VehicleMaintenanceRecord', 'vehicles.VehicleFuelLog',
    'vehicles.VehicleAssignment', 'vehicles.VehicleServiceProvider', 'vehicles.VehicleServiceSchedule',
    'locations.Location', 'locations.WAN',
    'field_ops.ClientSiteGeofence', 'field_ops.OrganizationFieldOpsSettings',
    'field_ops.TimeclockEntry', 'field_ops.GeofenceVisit',
    'reports.ScheduledReport', 'reports.SavedQuery',
    'processes.Process', 'processes.ProcessStage',
]


def _counts():
    return {label: apps.get_model(label).objects.count() for label in SEEDED}


def _seed():
    out = StringIO()
    call_command('seed_module_samples', only=['operations'], stdout=out)
    return out.getvalue()


class OperationsSamplesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for slug in CUSTOMER_SLUGS + (MSP_SLUG,):
            Organization.objects.create(name=slug.replace('-', ' ').title(), slug=slug)
        cls.admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'pw-not-used')
        _seed()

    def test_every_model_seeded_and_second_run_adds_nothing(self):
        before = _counts()
        for label, n in before.items():
            self.assertGreater(n, 0, label)
        out = _seed()
        self.assertEqual(_counts(), before)
        self.assertIn('0 rows created', out)

    def test_nothing_left_for_timers_to_act_on(self):
        from field_ops.models import TechnicianLocation, TimeclockEntry
        from locations.models import WAN, WANCheck
        from reports.models import ScheduledReport
        from scheduling.models import ScheduledTask, SchedulerWallboard
        self.assertFalse(ScheduledTask.objects.filter(alert_email=True).exists())
        self.assertFalse(ScheduledTask.objects.filter(alert_sms=True).exists())
        self.assertFalse(WAN.objects.filter(monitoring_enabled=True).exists())
        self.assertFalse(WANCheck.objects.exists())
        self.assertFalse(ScheduledReport.objects.filter(is_active=True).exists())
        self.assertFalse(SchedulerWallboard.objects.filter(is_enabled=True).exists())
        self.assertFalse(TimeclockEntry.objects.filter(clocked_out_at__isnull=True).exists())
        self.assertFalse(TechnicianLocation.objects.exists())
        for wan in WAN.objects.all():
            self.assertTrue(wan.static_ip.startswith(('203.0.113.', '198.51.100.')), wan.static_ip)

    def test_superuser_gets_no_resourcing_rows(self):
        from resourcing.models import LeaveRequest, TechCostRate, UserSkill, WorkingHours
        for model in (UserSkill, WorkingHours, LeaveRequest, TechCostRate):
            self.assertFalse(model.objects.filter(user=self.admin).exists(), model.__name__)

    def test_inventory_history_ends_at_current_quantity(self):
        from inventory.models import InventoryItem
        for item in InventoryItem.objects.all():
            self.assertEqual(item.transactions.order_by('-created_at').first().quantity_after, item.quantity)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OperationsSamplePagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for slug in CUSTOMER_SLUGS + (MSP_SLUG,):
            Organization.objects.create(name=slug.replace('-', ' ').title(), slug=slug)
        cls.admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'pw-not-used')
        _seed()

    def _get_as(self, org_slug, names):
        self.client.force_login(self.admin)
        session = self.client.session
        session['current_organization_id'] = Organization.objects.get(slug=org_slug).pk
        session.save()
        for name in names:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_msp_pages(self):
        self._get_as(MSP_SLUG, [
            'inventory:inventory_dashboard', 'inventory:item_list', 'inventory:tool_list',
            'inventory:transaction_list', 'inventory:low_stock_report',
            'resourcing:tech_roster', 'resourcing:holiday_list', 'resourcing:leave_approvals',
            'resourcing:tech_cost_rate_list', 'resourcing:capacity_report',
            'vehicles:vehicles_dashboard', 'vehicles:vehicle_list',
        ])

    def test_customer_pages(self):
        self._get_as(CUSTOMER_SLUGS[0], [
            'scheduling:scheduling_dashboard', 'scheduling:task_list',
            'field_ops:timeclock_dashboard',
        ])
