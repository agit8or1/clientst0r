"""Server-side authorization regressions for field ops (roles/permissions
program): org-scoped field-ops settings, and the auto-time job re-checking the
technician's access every time it acts."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization
from field_ops.models import (
    AutoTimePreference, ClientSiteGeofence, OrganizationFieldOpsSettings, TechnicianLocation,
)
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FieldOpsSettingsOrgScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='FO A', slug='authz-fo-a')
        cls.b = Organization.objects.create(name='FO B', slug='authz-fo-b')
        cls.admin_a = User.objects.create_user('fo-admin-a', 'a@a.test', 'pw')
        Membership.objects.create(user=cls.admin_a, organization=cls.a, role=Role.ADMIN)

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.admin_a)

    def test_admin_of_a_cannot_change_b(self):
        r = self.c.post('/field-ops/settings/', {
            'organization_id': self.b.pk, 'geofence_only_mode': 'on', 'retention_days': '1'})
        self.assertEqual(r.status_code, 200)  # "no organization" page
        self.assertFalse(OrganizationFieldOpsSettings.objects.filter(organization=self.b).exists())
        r = self.c.get(f'/field-ops/settings/?org={self.b.pk}')
        self.assertNotContains(r, 'FO B')

    def test_admin_of_a_changes_a(self):
        r = self.c.post('/field-ops/settings/', {
            'organization_id': self.a.pk, 'geofence_only_mode': 'on', 'retention_days': '30'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(OrganizationFieldOpsSettings.objects.get(organization=self.a).retention_days, 30)


class AutoTimeRechecksAccessTests(TestCase):

    def setUp(self):
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
        )
        self.user = _make_msp_tech(User.objects.create_user('fo-auto', password='x'))
        self.org = Organization.objects.create(name='FO Auto', slug='authz-fo-auto')
        ClientSiteGeofence.objects.create(
            organization=self.org, name='HQ', kind='radius',
            center_lat=Decimal('40.0'), center_lon=Decimal('-73.0'),
            radius_meters=200, active=True)
        st = TicketStatus.objects.create(name='New', slug='new', sort_order=1)
        pr = TicketPriority.objects.create(code='P3', name='Normal')
        tt = TicketType.objects.create(name='Incident', slug='incident')
        qu = Queue.objects.create(name='Default', slug='default')
        ticket = Ticket.objects.create(organization=self.org, subject='S', status=st,
                                       priority=pr, ticket_type=tt, queue=qu)
        TicketTimeEntry.objects.create(
            ticket=ticket, user=self.user, started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1), is_billable=True)
        AutoTimePreference.objects.create(user=self.user, mode='always_on')
        TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('40.0'), lon=Decimal('-73.0'), timestamp=timezone.now())

    def _running(self):
        from psa.models import TicketTimeEntry
        return TicketTimeEntry.objects.filter(user=self.user, ended_at__isnull=True).count()

    def test_deactivated_tech_gets_no_time_started(self):
        self.user.is_active = False
        self.user.save()
        call_command('auto_document_field_visits', stdout=StringIO())
        self.assertEqual(self._running(), 0)

    def test_tech_demoted_to_customer_gets_no_time_started(self):
        from accounts.models import UserType
        self.user.profile.user_type = UserType.ORG_USER
        self.user.profile.save()
        call_command('auto_document_field_visits', stdout=StringIO())
        self.assertEqual(self._running(), 0)

    def test_active_tech_still_gets_time(self):
        call_command('auto_document_field_visits', stdout=StringIO())
        self.assertEqual(self._running(), 1)
