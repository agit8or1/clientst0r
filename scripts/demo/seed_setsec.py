"""Fill the Administration -> Security pages of the demo: vulnerability scan
history, firewall rules and a blocked-request log, and RMM permission
overrides, so the Security guide (docs/SECURITY_SETTINGS.md) has something to
show.

Isolated demo database only. Idempotent: rows are matched on invented
identifiers and replaced. Every address is from the documentation ranges
(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24). The firewall switches stay
OFF: only rules and log rows are written, so the demo server's own requests
are never filtered. Nothing runs a scanner, calls Snyk or touches the host.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.utils import timezone

db_name = str(dj_settings.DATABASES['default'].get('NAME', ''))
if 'demo' not in db_name:
    sys.exit(f'refusing to seed a database that does not look like a demo one: {db_name}')

from core.models import (FirewallCountryRule, FirewallIPRule, FirewallLog, FirewallSettings, Organization,
                         PythonPackageScan, SnykScan)

User = get_user_model()
now = timezone.now()
lead = User.objects.get(username='demo.tech')
lena = User.objects.get(username='demo.lchen')
priya = User.objects.get(username='demo.ipatel')
marcus = User.objects.get(username='demo.mokafor')


# --- vulnerability scans (rows only; no scanner runs) ------------------------
SCANS = [
    # scan_id, type, status, days ago, (critical, high, medium, low), seconds
    ('demo-setsec-os-1', 'open_source', 'completed', 0.2, (0, 2, 3, 1), 74),
    ('demo-setsec-code-1', 'code', 'completed', 0.2, (0, 1, 4, 2), 141),
    ('demo-setsec-iac-1', 'iac', 'completed', 0.2, (0, 0, 1, 0), 22),
    ('demo-setsec-os-0', 'open_source', 'completed', 1.2, (1, 3, 3, 1), 69),
    ('demo-setsec-code-0', 'code', 'failed', 1.2, (0, 0, 0, 0), 9),
    ('demo-setsec-os-p', 'open_source', 'completed', 8, (1, 4, 5, 2), 80),
]
for scan_id, kind, status, days, (c, h, m, lo), secs in SCANS:
    SnykScan.objects.filter(scan_id=scan_id).delete()
    s = SnykScan.objects.create(
        scan_id=scan_id, scan_type=kind, status=status, severity_threshold='low',
        critical_count=c, high_count=h, medium_count=m, low_count=lo, total_vulnerabilities=c + h + m + lo,
        duration_seconds=secs, triggered_by=lead,
        error_message=('Snyk Code is not enabled for this Snyk organization (demo).' if status == 'failed' else ''),
        vulnerabilities={})
    started = now - timedelta(days=days)
    SnykScan.objects.filter(pk=s.pk).update(started_at=started, completed_at=started + timedelta(seconds=secs))

PythonPackageScan.objects.filter(scan_error='demo-setsec').delete()
if not PythonPackageScan.objects.exists():
    PythonPackageScan.objects.create(total_packages=212, vulnerable_packages=1, total_vulnerabilities=1,
                                     medium_count=1, scan_succeeded=True, scan_data={})

# --- firewall rules and log (switches stay off) -----------------------------
fw = FirewallSettings.get_settings()
assert not fw.ip_firewall_enabled and not fw.geoip_firewall_enabled, 'demo firewall must stay off'

IP_RULES = [
    ('203.0.113.0/24', 'Office network (demo)', True),
    ('198.51.100.25', 'Technician home connection (demo)', True),
    ('192.0.2.44', 'Former contractor VPN, kept for reference (demo)', False),
]
FirewallIPRule.objects.filter(description__endswith='(demo)').delete()
for ip, desc, active in IP_RULES:
    FirewallIPRule.objects.create(ip_address=ip, description=desc, is_active=active, created_by=lead)

FirewallCountryRule.objects.filter(created_by=lead).delete()
for code, name, surface in (('US', 'United States', 'staff'), ('CA', 'Canada', 'staff'),
                            ('US', 'United States', 'portal'), ('CA', 'Canada', 'portal'),
                            ('GB', 'United Kingdom', 'portal')):
    FirewallCountryRule.objects.create(country_code=code, country_name=name, surface=surface, created_by=lead)

FirewallLog.objects.filter(user_agent='demo-setsec').delete()
LOG = [
    ('198.51.100.77', 'NL', 'Netherlands', 'country_not_in_allowlist', '/account/login/', 'POST', 'staff', 0.1),
    ('203.0.113.250', 'BR', 'Brazil', 'country_not_in_allowlist', '/portal/login/', 'GET', 'portal', 0.4),
    ('192.0.2.180', '', '', 'ip_not_in_allowlist', '/core/dashboard/', 'GET', 'staff', 1.5),
    ('198.51.100.77', 'NL', 'Netherlands', 'country_not_in_allowlist', '/account/login/', 'GET', 'staff', 2.0),
    ('203.0.113.9', 'SG', 'Singapore', 'country_not_in_allowlist', '/api/v1/', 'GET', 'staff', 30),
]
for ip, cc, cn, reason, path, method, surface, hours in LOG:
    row = FirewallLog.objects.create(ip_address=ip, country_code=cc, country_name=cn, block_reason=reason,
                                     request_path=path, request_method=method, surface=surface,
                                     user_agent='demo-setsec')
    FirewallLog.objects.filter(pk=row.pk).update(timestamp=now - timedelta(hours=hours))

# --- RMM permission overrides ----------------------------------------------
from rmm_permissions import overrides
from rmm_permissions.models import RMMPermissionOverride as O

northwind = Organization.objects.get(name='Northwind Logistics')
ridgeline = Organization.objects.get(name='Ridgeline Dental Group')
O.objects.filter(reason__endswith='(demo)').delete()
overrides.create(lead, action='patch.deploy', effect=O.DENY, organization=ridgeline,
                 reason='Practice-management upgrade freeze until 1 December (demo)',
                 expires_at=now + timedelta(days=6))
overrides.create(lead, action='device.administer', effect=O.REQUIRE_APPROVAL, organization=northwind,
                 approval_level='l3', reason='Warehouse scanners: L3 sign-off for device changes (demo)')
overrides.create(lead, action='script.run_scoped', effect=O.ALLOW, organization=northwind, user=priya,
                 reason='Run the label-printer reset script during the move (demo)',
                 expires_at=now + timedelta(days=14))

print('setsec: scans', SnykScan.objects.filter(scan_id__startswith='demo-setsec').count(),
      '| ip rules', FirewallIPRule.objects.count(), '| country rules', FirewallCountryRule.objects.count(),
      '| blocked log', FirewallLog.objects.count(), '| rmm overrides', O.objects.count())
