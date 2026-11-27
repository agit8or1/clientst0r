"""Seed the demo with what the integration, API-key and import guides show:
a few inactive integration connections on invented `.example` hosts, API keys of
different scopes (secrets are random and discarded; only the prefix is stored in
the clear), and finished data-import jobs.

Isolated demo database only. Idempotent. Nothing here contacts any outside service:
every connection has sync switched off and an invented host.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import Role
from api.models import APIKey, APIKeyScope
from core.models import Organization
from imports.models import ImportJob
from integrations.models import PSAConnection, RMMConnection

User = get_user_model()
now = timezone.now()
tech = User.objects.get(username='demo.tech')
nw = Organization.objects.get(name='Northwind Logistics')

# --- Integrations (platform-owned, nothing syncs) ---
psa, _ = PSAConnection.objects.get_or_create(
    organization=None, name='Beacon PSA', defaults=dict(
        provider_type='connectwise_manage', base_url='https://psa.beaconmanaged.example',
        sync_enabled=False, is_active=True, last_sync_status='success',
        last_sync_at=now - timedelta(minutes=40)))
PSAConnection.objects.get_or_create(
    organization=None, name='Helpdesk (HaloPSA)', defaults=dict(
        provider_type='halo_psa', base_url='https://helpdesk.beaconmanaged.example',
        sync_enabled=False, is_active=True, last_sync_status='error',
        last_error='401 Unauthorized: the API application was disabled in the PSA.',
        last_sync_at=now - timedelta(hours=3)))
RMMConnection.objects.get_or_create(
    organization=None, name='Beacon RMM (NinjaOne)', defaults=dict(
        provider_type='ninjaone', base_url='https://app.ninjarmm.example',
        sync_enabled=False, sync_alerts=False, is_active=True, last_sync_status='success',
        last_sync_at=now - timedelta(minutes=15)))

# --- API keys (invented; the secret is generated and thrown away) ---
KEYS = [
    ('Reporting dashboard', Role.READONLY, APIKeyScope.ALL, 12, None, 'successful'),
    ('Browser extension (Jordan)', Role.EDITOR, APIKeyScope.SINGLE, 2, None, 'unused'),
    ('Nightly asset sync', Role.EDITOR, APIKeyScope.DESCENDANTS, 1, 25, 'successful'),
    ('Old test key', Role.READONLY, APIKeyScope.SINGLE, 0, None, 'off'),
]
for name, role, scope, used_days_ago, expires_days, kind in KEYS:
    if APIKey.objects.filter(organization=nw, name=name).exists():
        continue
    key, _plain = APIKey.create_key(nw, tech, name, role=role, scope=scope)
    upd = {}
    if kind in ('successful',):
        upd.update(last_used_at=now - timedelta(days=used_days_ago, hours=1), last_used_ip='203.0.113.25')
    if expires_days:
        upd['expires_at'] = now + timedelta(days=expires_days)
    if kind == 'off':
        upd['is_active'] = False
    if upd:
        APIKey.objects.filter(pk=key.pk).update(**upd)

# --- Import jobs (finished; never run) ---
def job(src, url, **kw):
    if ImportJob.objects.filter(source_type=src, source_url=url).exists():
        return
    ImportJob.objects.create(source_type=src, source_url=url, started_by=tech, **kw)

job('itglue', 'https://api.itglue.example', target_organization=None, status='completed', dry_run=True,
    started_at=now - timedelta(days=3, minutes=9), completed_at=now - timedelta(days=3),
    total_items=412, items_imported=398, items_skipped=14, items_failed=0,
    organizations_created=3, organizations_matched=2, import_contacts=True, import_locations=True,
    import_log='[dry run] 5 organizations, 398 records would be imported, 14 already exist.\n')
job('hudu', 'https://docs.beaconmanaged.example', target_organization=nw, status='completed_with_errors',
    dry_run=False, started_at=now - timedelta(days=1, minutes=6), completed_at=now - timedelta(days=1),
    total_items=96, items_imported=90, items_skipped=4, items_failed=2,
    import_log='2 assets failed: missing name.\n')
print('x3 seed done:', PSAConnection.objects.count(), 'PSA,', APIKey.objects.count(), 'keys,', ImportJob.objects.count(), 'jobs')
