"""
field_ops tests — Phase 8 (GPS auto-time + Timeclock + privacy).
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import Organization

from .models import (
    ClientSiteGeofence,
    LocationRetentionPolicy,
    MobileDevice,
    TechnicianLocation,
    TimeclockEntry,
)


class TechnicianLocationTests(TestCase):
    """v3.17.386 — TechnicianLocation model."""

    def setUp(self):
        self.user = User.objects.create_user(username='tech1', password='x')

    def test_create_location_sets_default_retention(self):
        loc = TechnicianLocation.objects.create(
            tech=self.user,
            lat=Decimal('40.123456'),
            lon=Decimal('-73.987654'),
            accuracy=15,
            source='mobile',
        )
        self.assertIsNotNone(loc.retention_until)
        # Default retention is ~90 days
        delta = (loc.retention_until - timezone.now().date()).days
        self.assertGreaterEqual(delta, 89)
        self.assertLessEqual(delta, 91)

    def test_explicit_retention_preserved(self):
        target = timezone.now().date() + timedelta(days=30)
        loc = TechnicianLocation.objects.create(
            tech=self.user,
            lat=Decimal('40.0'),
            lon=Decimal('-73.0'),
            retention_until=target,
        )
        self.assertEqual(loc.retention_until, target)


class ClientSiteGeofenceTests(TestCase):
    """v3.17.386 — ClientSiteGeofence containment math."""

    def setUp(self):
        self.org = Organization.objects.create(name='Acme Corp')

    def test_radius_geofence_contains_point(self):
        # 100m radius around (40.0, -73.0). Same point -> inside.
        fence = ClientSiteGeofence.objects.create(
            organization=self.org,
            name='Acme HQ',
            kind='radius',
            center_lat=Decimal('40.000000'),
            center_lon=Decimal('-73.000000'),
            radius_meters=100,
        )
        self.assertTrue(fence.contains(Decimal('40.000000'), Decimal('-73.000000')))

    def test_radius_geofence_excludes_distant_point(self):
        fence = ClientSiteGeofence.objects.create(
            organization=self.org,
            name='Acme HQ',
            kind='radius',
            center_lat=Decimal('40.000000'),
            center_lon=Decimal('-73.000000'),
            radius_meters=100,
        )
        # ~100km away — definitely outside
        self.assertFalse(fence.contains(Decimal('41.000000'), Decimal('-74.000000')))

    def test_polygon_geofence_contains_point(self):
        # Square around (40,-73) of width 0.01 deg (~1.1km)
        fence = ClientSiteGeofence.objects.create(
            organization=self.org,
            name='Acme campus',
            kind='polygon',
            polygon_json=[
                [40.005, -73.005],
                [40.005, -72.995],
                [39.995, -72.995],
                [39.995, -73.005],
            ],
        )
        self.assertTrue(fence.contains(Decimal('40.0'), Decimal('-73.0')))
        self.assertFalse(fence.contains(Decimal('41.0'), Decimal('-73.0')))

    def test_admin_str(self):
        fence = ClientSiteGeofence.objects.create(
            organization=self.org,
            name='HQ',
            kind='radius',
            center_lat=Decimal('40.0'),
            center_lon=Decimal('-73.0'),
            radius_meters=100,
        )
        self.assertIn('HQ', str(fence))


class TimeclockEntryTests(TestCase):
    """v3.17.409 — TimeclockEntry model + auto-derive TicketTimeEntry."""

    def setUp(self):
        self.user = User.objects.create_user(username='tech-tc', password='x')
        self.org = Organization.objects.create(name='TC Org')

    def test_open_entry_no_clock_out(self):
        entry = TimeclockEntry.objects.create(
            tech=self.user, organization=self.org, source='mobile',
        )
        self.assertIsNone(entry.clocked_out_at)
        self.assertEqual(entry.duration_minutes, 0)

    def test_unique_open_entry_per_tech(self):
        TimeclockEntry.objects.create(tech=self.user, organization=self.org)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TimeclockEntry.objects.create(tech=self.user, organization=self.org)

    def test_clock_out_with_ticket_derives_time_entry(self):
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        status_new = TicketStatus.objects.create(name='New', slug='new', sort_order=1)
        priority = TicketPriority.objects.create(code='P3', name='Normal')
        ttype = TicketType.objects.create(name='Incident', slug='incident')
        queue = Queue.objects.create(name='Default', slug='default')
        ticket = Ticket.objects.create(
            organization=self.org,
            subject='TC test ticket',
            status=status_new, priority=priority,
            ticket_type=ttype, queue=queue,
        )
        start = timezone.now() - timedelta(hours=1)
        entry = TimeclockEntry.objects.create(
            tech=self.user, organization=self.org,
            ticket=ticket, clocked_in_at=start, source='mobile',
        )
        self.assertIsNone(entry.derived_time_entry)
        # Clock out
        entry.clocked_out_at = timezone.now()
        entry.save()
        entry.refresh_from_db()
        self.assertIsNotNone(entry.derived_time_entry_id)
        self.assertEqual(entry.derived_time_entry.ticket_id, ticket.pk)

    def test_clock_out_without_ticket_no_derive(self):
        start = timezone.now() - timedelta(minutes=30)
        entry = TimeclockEntry.objects.create(
            tech=self.user, organization=self.org,
            clocked_in_at=start, source='mobile',
        )
        entry.clocked_out_at = timezone.now()
        entry.save()
        entry.refresh_from_db()
        self.assertIsNone(entry.derived_time_entry)


class MobileDeviceTests(TestCase):
    """v3.17.409 — MobileDevice model."""

    def setUp(self):
        self.user = User.objects.create_user(username='tech-md', password='x')

    def test_create_device(self):
        device = MobileDevice.objects.create(
            user=self.user,
            device_id=uuid.uuid4(),
            platform='android',
            name='Pixel 9',
        )
        self.assertFalse(device.revoked)
        self.assertEqual(device.platform, 'android')

    def test_unique_device_id(self):
        did = uuid.uuid4()
        MobileDevice.objects.create(user=self.user, device_id=did, platform='ios')
        u2 = User.objects.create_user(username='tech-md2', password='x')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MobileDevice.objects.create(user=u2, device_id=did, platform='ios')


class LocationRetentionPolicyTests(TestCase):
    """v3.17.411 — LocationRetentionPolicy model + prune mgmt cmd."""

    def setUp(self):
        self.user = User.objects.create_user(username='tech-rp', password='x')
        self.org = Organization.objects.create(name='RP Org')

    def test_policy_created_with_defaults(self):
        policy = LocationRetentionPolicy.objects.create(organization=self.org)
        self.assertEqual(policy.retention_days, 90)
        self.assertFalse(policy.apply_to_geofence_only)

    def test_prune_deletes_expired_rows(self):
        from io import StringIO
        from django.core.management import call_command
        # Expired row
        expired = TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('40.0'), lon=Decimal('-73.0'),
            retention_until=timezone.now().date() - timedelta(days=1),
        )
        # Fresh row
        fresh = TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('40.1'), lon=Decimal('-73.1'),
            retention_until=timezone.now().date() + timedelta(days=10),
        )
        out = StringIO()
        call_command('prune_technician_locations', stdout=out)
        self.assertIn('Deleted 1', out.getvalue())
        self.assertFalse(TechnicianLocation.objects.filter(pk=expired.pk).exists())
        self.assertTrue(TechnicianLocation.objects.filter(pk=fresh.pk).exists())

    def test_prune_dry_run_keeps_rows(self):
        from io import StringIO
        from django.core.management import call_command
        TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('40.0'), lon=Decimal('-73.0'),
            retention_until=timezone.now().date() - timedelta(days=5),
        )
        out = StringIO()
        call_command('prune_technician_locations', '--dry-run', stdout=out)
        self.assertIn('Would delete 1', out.getvalue())
        self.assertEqual(TechnicianLocation.objects.count(), 1)

    def test_prune_no_op_when_nothing_expired(self):
        from io import StringIO
        from django.core.management import call_command
        TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('40.0'), lon=Decimal('-73.0'),
        )
        out = StringIO()
        call_command('prune_technician_locations', stdout=out)
        self.assertIn('Deleted 0', out.getvalue())


class AutoDocumentFieldVisitsTests(TestCase):
    """v3.17.412 — GPS auto-documentation engine (Sub-phase 8.2)."""

    def setUp(self):
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
        )
        self.user = User.objects.create_user(username='tech-eng', password='x')
        self.org = Organization.objects.create(name='Eng Org')
        self.fence = ClientSiteGeofence.objects.create(
            organization=self.org, name='HQ', kind='radius',
            center_lat=Decimal('40.0'), center_lon=Decimal('-73.0'),
            radius_meters=200, active=True,
        )
        # Build a ticket so the engine has something to start time against.
        sn = TicketStatus.objects.create(name='New', slug='new', sort_order=1)
        pr = TicketPriority.objects.create(code='P3', name='Normal')
        tt = TicketType.objects.create(name='Incident', slug='incident')
        qu = Queue.objects.create(name='Default', slug='default')
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Eng', status=sn,
            priority=pr, ticket_type=tt, queue=qu,
        )
        # Plant an unsubmitted TicketTimeEntry so _last_active_ticket finds it.
        TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.user,
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
            is_billable=True,
        )

    def _ping_inside(self):
        return TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('40.0'), lon=Decimal('-73.0'),
            timestamp=timezone.now(),
        )

    def _ping_outside(self):
        return TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('41.5'), lon=Decimal('-74.5'),
            timestamp=timezone.now(),
        )

    def test_off_mode_skips_user(self):
        from io import StringIO
        from django.core.management import call_command
        from .models import AutoTimePreference
        AutoTimePreference.objects.create(user=self.user, mode='off')
        self._ping_inside()
        out = StringIO()
        call_command('auto_document_field_visits', stdout=out)
        # No new running TicketTimeEntry
        from psa.models import TicketTimeEntry
        self.assertFalse(
            TicketTimeEntry.objects.filter(user=self.user, ended_at__isnull=True).exists()
        )

    def test_always_on_enter_creates_running_entry(self):
        from io import StringIO
        from django.core.management import call_command
        from .models import AutoTimePreference
        AutoTimePreference.objects.create(user=self.user, mode='always_on')
        self._ping_inside()
        out = StringIO()
        call_command('auto_document_field_visits', stdout=out)
        from psa.models import TicketTimeEntry
        running = TicketTimeEntry.objects.filter(
            user=self.user, ended_at__isnull=True, ticket=self.ticket,
        )
        self.assertEqual(running.count(), 1)
        self.assertIn('[auto-time:field_ops]', running.first().notes)

    def test_always_on_exit_closes_entry(self):
        from io import StringIO
        from django.core.management import call_command
        from .models import AutoTimePreference
        AutoTimePreference.objects.create(user=self.user, mode='always_on')
        # Step 1: enter
        self._ping_inside()
        call_command('auto_document_field_visits', stdout=StringIO())
        # Step 2: drop a fresh outside ping so latest is OUTSIDE
        self._ping_outside()
        call_command('auto_document_field_visits', stdout=StringIO())
        from psa.models import TicketTimeEntry
        running = TicketTimeEntry.objects.filter(
            user=self.user, ended_at__isnull=True,
        )
        self.assertEqual(running.count(), 0)

    def test_ask_first_creates_pending_no_time_entry(self):
        from io import StringIO
        from django.core.management import call_command
        from .models import AutoTimePreference, PendingAutoTime
        AutoTimePreference.objects.create(user=self.user, mode='ask_first')
        self._ping_inside()
        call_command('auto_document_field_visits', stdout=StringIO())
        # PendingAutoTime row exists
        self.assertEqual(
            PendingAutoTime.objects.filter(user=self.user, confirmed_at__isnull=True).count(),
            1,
        )
        # No running TicketTimeEntry yet (ask_first defers)
        from psa.models import TicketTimeEntry
        self.assertFalse(
            TicketTimeEntry.objects.filter(user=self.user, ended_at__isnull=True).exists()
        )

    def test_no_recent_ping_skips_user(self):
        from io import StringIO
        from django.core.management import call_command
        from .models import AutoTimePreference
        AutoTimePreference.objects.create(user=self.user, mode='always_on')
        # Stale ping (1 hour ago)
        TechnicianLocation.objects.create(
            tech=self.user, lat=Decimal('40.0'), lon=Decimal('-73.0'),
            timestamp=timezone.now() - timedelta(hours=1),
        )
        out = StringIO()
        call_command('auto_document_field_visits', stdout=out)
        self.assertIn('skipped=1', out.getvalue())


# ---------------------------------------------------------------------------
# v3.17.413 — Timeclock dashboard + payroll export views
# ---------------------------------------------------------------------------

from django.conf import settings as _django_settings
from django.test import Client, override_settings

_TEST_MIDDLEWARE = [
    m for m in _django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


_TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(
    MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
    STORAGES=_TEST_STORAGES,
)
class TimeclockDashboardTests(TestCase):
    """v3.17.413 — staff-only timeclock dashboard + CSV payroll export."""

    def setUp(self):
        self.staff = User.objects.create_user(
            username='staff', password='x', is_staff=True,
        )
        self.tech = User.objects.create_user(username='tech-d', password='x')
        self.guest = User.objects.create_user(username='guest', password='x')
        self.org = Organization.objects.create(name='Dash Org')
        self.client = Client()

    def test_non_staff_blocked(self):
        self.client.force_login(self.guest)
        resp = self.client.get('/field-ops/timeclock/')
        self.assertEqual(resp.status_code, 403)

    def test_staff_dashboard_shows_open_entries(self):
        TimeclockEntry.objects.create(
            tech=self.tech, organization=self.org, source='web',
        )
        self.client.force_login(self.staff)
        resp = self.client.get('/field-ops/timeclock/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'tech-d')
        self.assertContains(resp, 'Dash Org')

    def test_payroll_export_csv_columns(self):
        # Closed entry to populate the export
        start = timezone.now() - timedelta(days=2, hours=1)
        end = timezone.now() - timedelta(days=2)
        TimeclockEntry.objects.create(
            tech=self.tech, organization=self.org,
            clocked_in_at=start, clocked_out_at=end, source='web',
        )
        self.client.force_login(self.staff)
        resp = self.client.get('/field-ops/timeclock/payroll-export.csv')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        body = resp.content.decode('utf-8')
        # Header row
        self.assertIn('tech,week_start,hours,overtime_hours,org', body)
        self.assertIn('tech-d', body)
        self.assertIn('Dash Org', body)


@override_settings(
    MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
    STORAGES=_TEST_STORAGES,
)
class MyLocationHistoryTests(TestCase):
    """v3.17.415 — per-tech location history view + delete actions."""

    def setUp(self):
        self.user = User.objects.create_user(username='hist-user', password='x')
        self.other = User.objects.create_user(username='other', password='x')
        # Three pings for our user, one for someone else
        for i in range(3):
            TechnicianLocation.objects.create(
                tech=self.user, lat=Decimal('40.0'), lon=Decimal('-73.0'),
            )
        TechnicianLocation.objects.create(
            tech=self.other, lat=Decimal('41.0'), lon=Decimal('-72.0'),
        )
        self.client = Client()

    def test_history_lists_only_my_rows(self):
        self.client.force_login(self.user)
        resp = self.client.get('/field-ops/my-location-history/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Total rows: <strong>3</strong>')

    def test_delete_one_row_only_my_own(self):
        self.client.force_login(self.user)
        # Try deleting another user's row — must 404
        other_pk = TechnicianLocation.objects.filter(tech=self.other).first().pk
        resp = self.client.post(f'/field-ops/my-location-history/{other_pk}/delete/')
        self.assertEqual(resp.status_code, 404)
        # Delete one of mine
        my_pk = TechnicianLocation.objects.filter(tech=self.user).first().pk
        resp2 = self.client.post(f'/field-ops/my-location-history/{my_pk}/delete/')
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(
            TechnicianLocation.objects.filter(tech=self.user).count(), 2,
        )

    def test_delete_all_requires_confirm_word(self):
        self.client.force_login(self.user)
        # Wrong confirmation — keeps rows
        resp = self.client.post(
            '/field-ops/my-location-history/delete-all/', {'confirm': 'NO'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            TechnicianLocation.objects.filter(tech=self.user).count(), 3,
        )
        # Correct confirmation — wipes
        resp2 = self.client.post(
            '/field-ops/my-location-history/delete-all/', {'confirm': 'DELETE'},
        )
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(
            TechnicianLocation.objects.filter(tech=self.user).count(), 0,
        )
        # Other user's row untouched
        self.assertEqual(
            TechnicianLocation.objects.filter(tech=self.other).count(), 1,
        )


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GeofenceOnlyModeTests(TestCase):
    """v3.17.415 — geofence-only-mode write at the locations endpoint."""

    def setUp(self):
        from api_mobile.models import MobileAuthToken
        from datetime import time as _time
        from resourcing.models import WorkingHours
        self.org = Organization.objects.create(name='Geo Org')
        self.user = User.objects.create_user('geo-tech', password='hunter2')
        # Always-on WorkingHours so we never get suppressed off-shift
        for wd in range(0, 7):
            WorkingHours.objects.create(
                user=self.user, weekday=wd,
                start_time=_time(0, 0), end_time=_time(23, 59),
            )
        self.token, _row = MobileAuthToken.issue(self.user)
        from .models import OrganizationFieldOpsSettings
        OrganizationFieldOpsSettings.objects.create(
            organization=self.org, geofence_only_mode=True,
        )
        self.fence = ClientSiteGeofence.objects.create(
            organization=self.org, name='HQ', kind='radius',
            center_lat=Decimal('40.0'), center_lon=Decimal('-73.0'),
            radius_meters=200, active=True,
        )

    def test_inside_geofence_writes_visit_not_location(self):
        from .models import GeofenceVisit
        import json
        resp = self.client.post(
            '/api/mobile/v1/locations/',
            data=json.dumps({'lat': '40.0', 'lon': '-73.0'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['mode'], 'geofence_only')
        # No raw row
        self.assertEqual(TechnicianLocation.objects.filter(tech=self.user).count(), 0)
        self.assertEqual(GeofenceVisit.objects.filter(user=self.user).count(), 1)

    def test_outside_geofence_writes_normal_row(self):
        from .models import GeofenceVisit
        import json
        # Far away — outside the 200m fence
        resp = self.client.post(
            '/api/mobile/v1/locations/',
            data=json.dumps({'lat': '41.5', 'lon': '-74.5'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        # Outside any geofence-only org -> regular TechnicianLocation row
        self.assertEqual(TechnicianLocation.objects.filter(tech=self.user).count(), 1)
        self.assertEqual(GeofenceVisit.objects.filter(user=self.user).count(), 0)


@override_settings(
    MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
    STORAGES=_TEST_STORAGES,
)
class FieldOpsSettingsViewTests(TestCase):
    """v3.17.416 — org-admin retention/privacy UI."""

    def setUp(self):
        self.org = Organization.objects.create(name='Set Org')
        self.staff = User.objects.create_user(
            'fset-staff', password='x', is_staff=True,
        )
        self.guest = User.objects.create_user('fset-guest', password='x')
        self.client = Client()

    def test_non_admin_blocked(self):
        self.client.force_login(self.guest)
        resp = self.client.get('/field-ops/settings/')
        self.assertEqual(resp.status_code, 403)

    def test_save_changes_persist_and_audit(self):
        from .models import OrganizationFieldOpsSettings
        from audit.models import AuditLog
        self.client.force_login(self.staff)
        # Initial GET creates a settings row
        resp = self.client.get(f'/field-ops/settings/?org={self.org.id}')
        self.assertEqual(resp.status_code, 200)
        # POST changes
        resp2 = self.client.post('/field-ops/settings/', {
            'organization_id': self.org.id,
            'geofence_only_mode': 'on',
            'retention_days': '45',
        })
        self.assertEqual(resp2.status_code, 302)
        s = OrganizationFieldOpsSettings.objects.get(organization=self.org)
        self.assertTrue(s.geofence_only_mode)
        self.assertEqual(s.retention_days, 45)
        # Audit row written
        rows = AuditLog.objects.filter(user=self.staff)
        self.assertTrue(any(
            (r.extra_data or {}).get('event') == 'org_field_ops_settings_changed'
            for r in rows
        ))
