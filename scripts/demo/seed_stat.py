"""Fill the configuration-backup pages for the status-page / config-backup guide.

Isolated demo database only. Devices, hosts (`.example`), firmware versions,
configs and the vault entry are invented. Nothing here connects to a device:
the targets point at `.example` hosts and the demo scheduler is not run.
Idempotent: re-running leaves existing rows alone.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.utils import timezone
from assets.models import Asset
from core.models import Organization
from netconfig.models import BackupTarget, ConfigBackup
from vault.models import Password, PasswordFolder

now = timezone.now()
nwl = Organization.objects.get(name='Northwind Logistics')

FW_BASE = """hostname NWL-FW01
interface wan1
 ip address dhcp
interface lan
 ip address 10.20.0.1 255.255.255.0
policy 10 allow lan wan1 any
policy 20 allow wan1 lan tcp/443
snmp community northwind-demo ro
ntp server 0.pool.example
"""
FW_V2 = FW_BASE.replace("policy 20 allow wan1 lan tcp/443", "policy 20 allow wan1 lan tcp/443\npolicy 30 allow wan1 lan tcp/8443")
FW_V3 = FW_V2.replace("ntp server 0.pool.example", "ntp server 0.pool.example\nntp server 1.pool.example")
SW_BASE = """hostname NWL-SW-CORE
vlan 10 name Office
vlan 20 name Warehouse
vlan 30 name Cameras
interface gi1/0/1
 switchport access vlan 10
interface gi1/0/2
 switchport access vlan 20
"""
SW_V2 = SW_BASE.replace("switchport access vlan 20", "switchport access vlan 30")

def snap(asset, body, days_ago, fw, source, approved=False, drift='', note=''):
    ts = now - timedelta(days=days_ago)
    b, created = ConfigBackup.record_for_asset(asset, body, source=source, captured_at=ts,
                                               firmware_version=fw, note=note)
    if created:
        b.is_approved = approved; b.drift_state = drift
        b.save(update_fields=['is_approved', 'drift_state'])
    return b

fw = Asset.objects.get(organization=nwl, name='NWL-FW01')
sw = Asset.objects.get(organization=nwl, name='NWL-SW-CORE')

if not ConfigBackup.objects.filter(asset=fw).exists():
    snap(fw, FW_BASE, 40, '7.2.4', 'manual', approved=True, drift='baseline', note='Pasted at onboarding')
    snap(fw, FW_V2, 12, '7.2.4', 'ssh', drift='expected')
    last = snap(fw, FW_V3, 2, '7.2.5', 'ssh', drift='unauthorized')
    last.last_seen_at = now - timedelta(hours=3); last.save(update_fields=['last_seen_at'])
if not ConfigBackup.objects.filter(asset=sw).exists():
    snap(sw, SW_BASE, 30, '17.9.3', 'manual', approved=True, drift='baseline')
    snap(sw, SW_V2, 5, '17.9.3', 'manual', drift='unauthorized', note='Camera port moved')

folder, _ = PasswordFolder.objects.get_or_create(name='Network', organization=nwl)
cred = Password.objects.filter(title='NWL-FW01 backup account', organization=nwl).first()
if cred is None:
    cred = Password(title='NWL-FW01 backup account', organization=nwl, folder=folder,
                    username='cfgbackup', password_type='network_device')
    cred.set_password('demo-not-a-real-secret')
    cred.save()

if not BackupTarget.objects.filter(asset=fw).exists():
    BackupTarget.objects.create(
        asset=fw, organization=nwl, host='fw01.northwind.example', port=22,
        username='cfgbackup', credential=cred, adapter='fortios', cadence_hours=24,
        host_key_type='ssh-ed25519', host_key='AAAAC3NzaC1lZDI1NTE5AAAAIDemoKeyNotReal000000000000000000000000',
        host_key_fingerprint='SHA256:DemoFingerprintNotARealKey0000000000000000',
        host_key_approved_at=now - timedelta(days=39),
        last_attempt_at=now - timedelta(hours=3), last_success_at=now - timedelta(hours=3))
if not BackupTarget.objects.filter(asset=sw).exists():
    BackupTarget.objects.create(
        asset=sw, organization=nwl, host='sw-core.northwind.example', username='cfgbackup',
        adapter='cisco_ios', is_enabled=True)
print('config backups:', ConfigBackup.objects.count(), 'targets:', BackupTarget.objects.count())

# A spare monitor so the status page's "Add a service" form has something to offer.
# `.example` host; the demo never runs the monitor checker.
from monitoring.models import WebsiteMonitor
if not WebsiteMonitor.objects.filter(organization=nwl, name='Northwind customer portal').exists():
    WebsiteMonitor.objects.create(organization=nwl, name='Northwind customer portal',
                                  url='https://portal.northwind.example', status='active')
    print('added spare monitor')

# The public status page gets a fixed, demo-only link so the guide figure's address
# (scripts/guide_screenshots.json, guide-stat-public) works on every rebuilt demo.
# Never do this on a real install: a real link is random and rotates.
from statuspage.models import StatusPage
DEMO_STATUS_TOKEN = 'demo-northwind-status-link-0000000000000000'
page = (StatusPage.objects.filter(organization=nwl, visibility=StatusPage.VISIBILITY_PUBLIC, is_enabled=True)
        .order_by('pk').first())
if page is not None and not StatusPage.lookup(DEMO_STATUS_TOKEN).filter(pk=page.pk).exists():
    page.set_token(DEMO_STATUS_TOKEN)
    page.save(update_fields=['token', 'token_hash'])
    print('status page link set to the demo address')
