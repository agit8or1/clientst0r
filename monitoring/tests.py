"""
Baseline test coverage for the monitoring/ app.

Cron-driven (uptime checks fire on schedule) + externally-facing
(WebsiteMonitor.check_status makes outbound HTTP requests). Silent
failures here = invisible monitoring loss. Plus IPAM (Subnet,
IPAddress, VLAN) used by network ops.

Coverage areas:
  * `WebsiteMonitor` model basics + `is_ssl_expiring_soon` /
    `is_domain_expiring_soon` properties.
  * `Expiration` model — `is_expired`, `days_until_expiration`,
    `is_expiring_soon` properties.
  * IPAM constraints — `IPAddress` `(subnet, ip_address)` is unique
    so the same address can't be allocated twice in one subnet.
  * OrganizationManager filtering on multi-tenant models.
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from monitoring.models import (
    Expiration,
    IPAddress,
    MonitorCheck,
    Subnet,
    VLAN,
    WebsiteMonitor,
)


# ---------------------------------------------------------------------------
# WebsiteMonitor — uptime + SSL/domain expiry tracking
# ---------------------------------------------------------------------------

class WebsiteMonitorModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='WMCo', slug='wm-co')

    def test_create_with_minimal_required_fields(self):
        wm = WebsiteMonitor.objects.create(
            organization=self.org, name='example.com', url='https://example.com',
        )
        self.assertEqual(wm.status, 'unknown')
        self.assertTrue(wm.is_enabled)
        self.assertEqual(wm.check_interval_minutes, 60)

    def test_str_includes_name_and_url(self):
        wm = WebsiteMonitor.objects.create(
            organization=self.org, name='example.com', url='https://example.com',
        )
        self.assertIn('example.com', str(wm))
        self.assertIn('https://example.com', str(wm))

    def test_ssl_expiring_soon_true_when_expiry_within_warning_window(self):
        wm = WebsiteMonitor.objects.create(
            organization=self.org, name='soon-ssl', url='https://soon.example',
            ssl_expires_at=timezone.now() + timedelta(days=10),
            ssl_warning_days=30,
        )
        self.assertTrue(wm.is_ssl_expiring_soon)

    def test_ssl_expiring_soon_false_when_far_from_expiry(self):
        wm = WebsiteMonitor.objects.create(
            organization=self.org, name='far-ssl', url='https://far.example',
            ssl_expires_at=timezone.now() + timedelta(days=180),
            ssl_warning_days=30,
        )
        self.assertFalse(wm.is_ssl_expiring_soon)

    def test_ssl_expiring_soon_false_when_expiry_unknown(self):
        # ssl_expires_at left null — the property must short-circuit to False
        # rather than raising on `None <= ...`.
        wm = WebsiteMonitor.objects.create(
            organization=self.org, name='unknown-ssl', url='https://unknown.example',
        )
        self.assertFalse(wm.is_ssl_expiring_soon)

    def test_domain_expiring_soon_uses_domain_warning_window(self):
        wm = WebsiteMonitor.objects.create(
            organization=self.org, name='dom', url='https://dom.example',
            domain_expires_at=timezone.now() + timedelta(days=45),
            domain_warning_days=60,
        )
        self.assertTrue(wm.is_domain_expiring_soon)

    def test_for_organization_filtering(self):
        org_b = Organization.objects.create(name='WMOther', slug='wm-other')
        WebsiteMonitor.objects.create(
            organization=self.org, name='a', url='https://a.example',
        )
        WebsiteMonitor.objects.create(
            organization=org_b, name='b', url='https://b.example',
        )
        for_a = list(WebsiteMonitor.objects.for_organization(self.org))
        self.assertEqual(len(for_a), 1)
        self.assertEqual(for_a[0].name, 'a')


# ---------------------------------------------------------------------------
# Expiration — generic expiry tracker for SSL / domain / license / etc.
# ---------------------------------------------------------------------------

class ExpirationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ExpCo', slug='exp-co')

    def test_str_format(self):
        future = timezone.now() + timedelta(days=30)
        e = Expiration.objects.create(
            organization=self.org, name='wildcard cert',
            expiration_type='ssl_cert', expires_at=future,
        )
        s = str(e)
        self.assertIn('wildcard cert', s)
        # Date portion is present (Y-M-D form).
        self.assertIn(future.strftime('%Y-%m-%d'), s)

    def test_is_expired_true_when_past(self):
        e = Expiration.objects.create(
            organization=self.org, name='gone',
            expiration_type='license',
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertTrue(e.is_expired)

    def test_is_expired_false_when_future(self):
        e = Expiration.objects.create(
            organization=self.org, name='good',
            expiration_type='license',
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.assertFalse(e.is_expired)

    def test_days_until_expiration_negative_when_expired(self):
        e = Expiration.objects.create(
            organization=self.org, name='gone',
            expiration_type='license',
            expires_at=timezone.now() - timedelta(days=5),
        )
        # `delta.days` truncates toward zero; for a 5-day-overdue expiry
        # the result is -5 (sometimes -6 depending on microseconds).
        self.assertLess(e.days_until_expiration, 0)

    def test_is_expiring_soon_only_when_within_warning_and_not_expired(self):
        # Within window — true.
        e_warn = Expiration.objects.create(
            organization=self.org, name='warn',
            expiration_type='license',
            expires_at=timezone.now() + timedelta(days=15),
            warning_days=30,
        )
        self.assertTrue(e_warn.is_expiring_soon)

        # Already expired — false (must be in [0, warning_days]).
        e_done = Expiration.objects.create(
            organization=self.org, name='done',
            expiration_type='license',
            expires_at=timezone.now() - timedelta(days=1),
            warning_days=30,
        )
        self.assertFalse(e_done.is_expiring_soon)

        # Outside window — false.
        e_far = Expiration.objects.create(
            organization=self.org, name='far',
            expiration_type='license',
            expires_at=timezone.now() + timedelta(days=180),
            warning_days=30,
        )
        self.assertFalse(e_far.is_expiring_soon)


# ---------------------------------------------------------------------------
# IPAM — VLAN, Subnet, IPAddress
# ---------------------------------------------------------------------------

class IPAMConstraintTests(TestCase):
    """The unique_together on (subnet, ip_address) is the dedupe contract
    that prevents the same address being allocated twice in one subnet."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='IPAMCo', slug='ipam-co')
        cls.subnet = Subnet.objects.create(
            organization=cls.org, name='LAN', network='192.168.1.0/24',
        )

    def test_same_ip_in_same_subnet_rejected(self):
        IPAddress.objects.create(subnet=self.subnet, ip_address='192.168.1.10')
        with self.assertRaises(IntegrityError), transaction.atomic():
            IPAddress.objects.create(subnet=self.subnet, ip_address='192.168.1.10')

    def test_same_ip_in_different_subnet_allowed(self):
        IPAddress.objects.create(subnet=self.subnet, ip_address='192.168.1.10')
        other_subnet = Subnet.objects.create(
            organization=self.org, name='DMZ', network='10.0.0.0/24',
        )
        # Same IP-string in a different subnet must NOT raise — the unique
        # is per-subnet, not global.
        IPAddress.objects.create(subnet=other_subnet, ip_address='192.168.1.10')

    def test_default_status_is_available(self):
        ip = IPAddress.objects.create(subnet=self.subnet, ip_address='192.168.1.20')
        self.assertEqual(ip.status, 'available')

    def test_str_with_hostname_includes_both(self):
        ip = IPAddress.objects.create(
            subnet=self.subnet, ip_address='192.168.1.30', hostname='gateway',
        )
        s = str(ip)
        self.assertIn('192.168.1.30', s)
        self.assertIn('gateway', s)

    def test_str_without_hostname_is_just_ip(self):
        ip = IPAddress.objects.create(subnet=self.subnet, ip_address='192.168.1.40')
        self.assertEqual(str(ip), '192.168.1.40')


class SubnetModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SubnetCo', slug='subnet-co')

    def test_str_includes_name_and_network(self):
        s = Subnet.objects.create(
            organization=self.org, name='LAN', network='192.168.1.0/24',
        )
        self.assertEqual(str(s), 'LAN (192.168.1.0/24)')

    def test_default_dns_servers_is_empty_list(self):
        s = Subnet.objects.create(
            organization=self.org, name='LAN', network='192.168.1.0/24',
        )
        self.assertEqual(s.dns_servers, [])

    def test_for_organization_filtering(self):
        org_b = Organization.objects.create(name='SubnetOther', slug='subnet-other')
        Subnet.objects.create(organization=self.org, name='A', network='10.0.0.0/24')
        Subnet.objects.create(organization=org_b, name='B', network='10.0.1.0/24')
        for_a = list(Subnet.objects.for_organization(self.org))
        self.assertEqual(len(for_a), 1)
        self.assertEqual(for_a[0].name, 'A')


class VLANModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='VLANCo', slug='vlan-co')

    def test_create_basic(self):
        v = VLAN.objects.create(
            organization=self.org, vlan_id=100, name='Voice',
        )
        self.assertEqual(v.vlan_id, 100)
        self.assertEqual(v.name, 'Voice')

    def test_str_includes_id_and_name(self):
        v = VLAN.objects.create(
            organization=self.org, vlan_id=200, name='Guest',
        )
        s = str(v)
        self.assertIn('200', s)
        self.assertIn('Guest', s)


from django.conf import settings as _django_settings
from django.test import Client, override_settings

from accounts.models import Membership, Role
from core.models import Organization
from monitoring.models import WebsiteMonitor

_TEST_MIDDLEWARE = [
    m for m in _django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WebsiteMonitorDeleteGlobalViewTests(TestCase):
    """v3.17.316 — privileged users in global view can delete monitors.
    Previously the delete view forced `organization=org` even when org
    was None, so every lookup 404'd in global view."""

    def setUp(self):
        self.org = Organization.objects.create(name='DelCo', slug='delco')
        self.staff = User.objects.create_user(
            'staffer', 'staff@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )
        self.member = User.objects.create_user(
            'member', 'm@x.com', 'pw',
        )
        Membership.objects.create(
            user=self.member, organization=self.org,
            role=Role.OWNER, is_active=True,
        )
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org, name='Test', url='https://example.com/',
        )
        self.client = Client()

    def _login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_staff_in_global_view_can_delete(self):
        # Login as staff WITHOUT pinning an org — global view
        self._login(self.staff)
        # Set is_staff_user header indirectly via a request middleware hook
        # is set when the user is in global view; for the test we just
        # rely on the user being is_superuser=True which the view checks.
        resp = self.client.post(
            f'/monitoring/websites/{self.monitor.pk}/delete/'
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(WebsiteMonitor.objects.filter(pk=self.monitor.pk).exists())

    def test_org_member_can_delete_their_orgs_monitor(self):
        self._login(self.member, self.org)
        resp = self.client.post(
            f'/monitoring/websites/{self.monitor.pk}/delete/'
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(WebsiteMonitor.objects.filter(pk=self.monitor.pk).exists())

    def test_org_member_cannot_delete_other_orgs_monitor(self):
        other_org = Organization.objects.create(name='Other', slug='other-org')
        # Login as the member (scoped to self.org), give them session for self.org
        self._login(self.member, self.org)
        # Create a monitor in OTHER org
        other_mon = WebsiteMonitor.objects.create(
            organization=other_org, name='Other', url='https://other.com/',
        )
        resp = self.client.post(
            f'/monitoring/websites/{other_mon.pk}/delete/'
        )
        # Org-scoped lookup should 404 because monitor belongs to other_org
        self.assertEqual(resp.status_code, 404)
        # And the monitor should still exist
        self.assertTrue(WebsiteMonitor.objects.filter(pk=other_mon.pk).exists())


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RackConnectionCreateViewTests(TestCase):
    """#136 — the rack detail page submits wiring connections as a JSON
    body via fetch(), but the view only read request.POST, so every field
    reported "This field is required." even when filled in."""

    def setUp(self):
        from monitoring.models import Rack, RackDevice
        self.org = Organization.objects.create(name='RackCo', slug='rackco')
        self.staff = User.objects.create_user(
            'rackadmin', 'rack@x.com', 'pw',
            is_staff=True, is_superuser=True,
        )
        self.rack = Rack.objects.create(organization=self.org, name='Closet', units=16)
        self.switch = RackDevice.objects.create(rack=self.rack, name='Switch', start_unit=1)
        self.firewall = RackDevice.objects.create(rack=self.rack, name='Firewall', start_unit=2)
        self.client = Client()
        self.client.force_login(self.staff)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def _payload(self):
        return {
            'from_device': self.switch.pk,
            'to_device': self.firewall.pk,
            'connection_type': 'network',
            'from_port': 'Gi1/0/1',
            'to_port': 'Gi1/0/2',
            'cable_color': '#0d6efd',
            'speed': '1Gbps',
        }

    def test_json_payload_creates_connection(self):
        from monitoring.models import RackConnection
        resp = self.client.post(
            f'/monitoring/devices/{self.switch.pk}/connections/create/',
            data=json.dumps(self._payload()),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'], body)
        self.assertTrue(
            RackConnection.objects.filter(
                from_device=self.switch, to_device=self.firewall
            ).exists()
        )

    def test_form_encoded_payload_still_works(self):
        """Classic (non-JS) form POSTs must keep working too."""
        from monitoring.models import RackConnection
        resp = self.client.post(
            f'/monitoring/devices/{self.switch.pk}/connections/create/',
            data=self._payload(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            RackConnection.objects.filter(from_device=self.switch).exists()
        )


# ---------------------------------------------------------------------------
# Phase 40.1 (v3.17.538) — check history + uptime
# ---------------------------------------------------------------------------

class MonitorCheckUptimeTests(TestCase):
    """Uptime is derived from MonitorCheck rows, not stored."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='UptimeCo', slug='uptime-co')
        cls.monitor = WebsiteMonitor.objects.create(
            organization=cls.org, name='Public site', url='https://example.com',
        )

    def _check(self, status, days_ago=0, hours_ago=0):
        return MonitorCheck.objects.create(
            monitor=self.monitor,
            checked_at=timezone.now() - timedelta(days=days_ago, hours=hours_ago),
            status=status,
        )

    def test_no_checks_gives_none_not_zero(self):
        """A monitor with no history has unknown uptime. Reporting 0% would
        read as a total outage and 100% as a clean record; both are wrong."""
        result = self.monitor.uptime(30)
        self.assertIsNone(result['percent'])
        self.assertEqual(result['checks'], 0)

    def test_all_up_is_100(self):
        for h in range(4):
            self._check('active', hours_ago=h)
        self.assertEqual(self.monitor.uptime(30)['percent'], 100.0)

    def test_down_checks_reduce_percentage(self):
        for h in range(9):
            self._check('active', hours_ago=h)
        self._check('down', hours_ago=9)
        result = self.monitor.uptime(30)
        self.assertEqual(result['checks'], 10)
        self.assertEqual(result['up'], 9)
        self.assertEqual(result['down'], 1)
        self.assertEqual(result['percent'], 90.0)

    def test_warning_counts_as_up(self):
        """A redirect or an expiring certificate means the site answered.
        Counting it as an outage would make the status page cry wolf."""
        self._check('active', hours_ago=1)
        self._check('warning', hours_ago=2)
        self.assertEqual(self.monitor.uptime(30)['percent'], 100.0)

    def test_window_excludes_older_checks(self):
        self._check('down', days_ago=40)
        self._check('active', hours_ago=1)
        thirty = self.monitor.uptime(30)
        self.assertEqual(thirty['checks'], 1)
        self.assertEqual(thirty['percent'], 100.0)
        ninety = self.monitor.uptime(90)
        self.assertEqual(ninety['checks'], 2)
        self.assertEqual(ninety['percent'], 50.0)

    def test_uptime_is_per_monitor(self):
        other = WebsiteMonitor.objects.create(
            organization=self.org, name='Other', url='https://other.example.com',
        )
        MonitorCheck.objects.create(
            monitor=other, checked_at=timezone.now(), status='down',
        )
        self._check('active', hours_ago=1)
        self.assertEqual(self.monitor.uptime(30)['percent'], 100.0)
        self.assertEqual(other.uptime(30)['percent'], 0.0)

    def test_is_up_property(self):
        self.assertTrue(self._check('active').is_up)
        self.assertTrue(self._check('warning').is_up)
        self.assertFalse(self._check('down').is_up)

    def test_checks_cascade_with_monitor(self):
        self._check('active')
        doomed = WebsiteMonitor.objects.create(
            organization=self.org, name='Doomed', url='https://doomed.example.com',
        )
        MonitorCheck.objects.create(
            monitor=doomed, checked_at=timezone.now(), status='active',
        )
        doomed.delete()
        self.assertEqual(MonitorCheck.objects.count(), 1)


class PruneMonitorChecksTests(TestCase):
    """The retention command keeps the window and drops the rest."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='PruneCo', slug='prune-co')
        cls.monitor = WebsiteMonitor.objects.create(
            organization=cls.org, name='Site', url='https://example.com',
        )

    def _seed(self):
        for days in (500, 450, 300, 10, 0):
            MonitorCheck.objects.create(
                monitor=self.monitor,
                checked_at=timezone.now() - timedelta(days=days),
                status='active',
            )

    def test_prune_removes_only_rows_past_retention(self):
        from django.core.management import call_command
        from io import StringIO
        self._seed()
        call_command('prune_monitor_checks', '--days', '400', stdout=StringIO())
        remaining = MonitorCheck.objects.count()
        self.assertEqual(remaining, 3)  # 300, 10, 0 days old survive

    def test_dry_run_deletes_nothing(self):
        from django.core.management import call_command
        from io import StringIO
        self._seed()
        out = StringIO()
        call_command('prune_monitor_checks', '--days', '400', '--dry-run', stdout=out)
        self.assertEqual(MonitorCheck.objects.count(), 5)
        self.assertIn('dry-run', out.getvalue())

    def test_default_retention_keeps_a_full_year(self):
        """400 days by default, so a 365-day uptime figure stays computable
        right up to the moment the prune runs."""
        from django.core.management import call_command
        from io import StringIO
        MonitorCheck.objects.create(
            monitor=self.monitor,
            checked_at=timezone.now() - timedelta(days=364),
            status='active',
        )
        call_command('prune_monitor_checks', stdout=StringIO())
        self.assertEqual(MonitorCheck.objects.count(), 1)
