"""Monitoring coverage for the demo (roadmap 82.15-82.20): sources in every
coverage state, the gaps in their history, and security alerts that were
delivered late after an outage.

Each source's history is played through the application's own recording
path (``events.source_health_store.record_collection``, which opens, extends
and recovers coverage windows) with the attempt times set in the past. The
backfill itself is not run (it would call the vendor); the window it would
have produced is written directly, and the late alerts are stored through
``ingest_polled_alert`` like a backfilled page would store them. Afterwards
no window is left pending, so the ``events_tick`` that setup_demo runs next
makes no request.

Isolated demo database only. Every name, host and finding is invented;
nothing is polled. Idempotent: a rerun removes and replays its own rows.

Sources and the state each one ends in:

* Defender - Northwind (security)        Active Monitoring; this morning a
  Partial Recovery: three alerts (one high) delivered late by the first read
  after a 3 h 40 min outage.
* Northwind - Proxmox Backup Server      Verified Quiet (or Active Monitoring
  while backup alerts are open); Recovered - Delivered Late two days ago
  (four backup runs), Recovered - None Missed six days ago and a Partial
  Recovery nine days ago.
* Ridgeline - Tactical RMM               Verified Quiet; an Unrecoverable Gap
  four days ago (the RMM keeps no alert history).
* Harbor Point - NinjaOne                Coverage Gap, open now (the RMM's API
  has answered 503 for the last 70 minutes).
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from backup_monitoring.models import BackupAlert, BackupConnection
from core.models import Organization
from events import coverage
from events import source_health as sh
from events import source_health_store as store
from events.models import CoverageWindow
from integrations.models import IntegrationSyncHealth, RMMAlert, RMMConnection
from security_alerts.adapters.base import ingest_polled_alert, late_note
from security_alerts.models import SecurityAlert, SecurityIncident, SecurityVendorConnection

now = timezone.now().replace(second=0, microsecond=0)
M = timedelta(minutes=1)
H = timedelta(hours=1)
D = timedelta(days=1)

msp = Organization.objects.get(name='Beacon Managed IT')
nwl = Organization.objects.get(name='Northwind Logistics')
rdg = Organization.objects.get(name='Ridgeline Dental Group')
hpc = Organization.objects.get(name='Harbor Point Credit Union')

defender = SecurityVendorConnection.objects.get(organization=msp, name='Defender - Northwind')
pbs = BackupConnection.objects.get(organization=nwl, name='Northwind — Proxmox Backup Server')
tactical = RMMConnection.objects.get(organization=rdg, name='Ridgeline — Tactical RMM')
ninja, _ = RMMConnection.objects.get_or_create(
    organization=hpc, name='Harbor Point — NinjaOne', provider_type='ninjaone',
    defaults=dict(base_url='https://ninja.harborpoint.example', sync_enabled=False, sync_alerts=False,
                  is_active=True))

SOURCES = [(defender, 'security'), (pbs, 'backup'), (tactical, 'rmm'), (ninja, 'rmm')]


def row_of(conn, kind):
    ct = ContentType.objects.get_for_model(type(conn))
    return IntegrationSyncHealth.objects.filter(content_type=ct, object_id=conn.pk, kind=kind).first()


# Replay from scratch: drop this script's own rows from an earlier run.
for conn, kind in SOURCES:
    row = row_of(conn, kind)
    if row is not None:
        CoverageWindow.objects.filter(source_key=coverage.source_key(row)).delete()
        row.delete()
old = SecurityAlert.objects.filter(connection=defender, external_id__startswith='demo-late-')
SecurityIncident.objects.filter(alerts__in=old).delete()
old.delete()

for conn, kind in SOURCES:
    # The connection's own freshness threshold: 12 hours, so the screenshots
    # taken some time after the build still show the sources as current.
    ct = ContentType.objects.get_for_model(type(conn))
    IntegrationSyncHealth.objects.get_or_create(
        content_type=ct, object_id=conn.pk, kind=kind,
        defaults={'organization_id': store.customer_of(conn), 'stale_after_minutes': 12 * 60, 'critical': True})


def ok(conn, kind, at, *, open_alerts=0, retrieved=0, times=()):
    return store.record_collection(conn, kind, sh.CollectionResult(
        attempted_at=at, window_start=at - 15 * M, window_end=at, retrieved=retrieved, processed=retrieved,
        committed=retrieved, verification=sh.V_PROBE, event_times=list(times), open_alerts=open_alerts,
        duration_ms=640), legacy_status=kind != 'rmm')


def fail(conn, kind, at, reason, diagnostic):
    return store.record_collection(conn, kind, sh.CollectionResult(
        attempted_at=at, window_start=at - 15 * M, window_end=at, reason=reason, diagnostic=diagnostic,
        duration_ms=10000), legacy_status=kind != 'rmm')


def outage(conn, kind, start, end, step, reason, diagnostic, recover=True):
    """A successful read before ``start``, failures every ``step`` until
    ``end`` (None = still failing), then the first successful read again
    (unless ``recover`` is False: the caller records it)."""
    ok(conn, kind, start - step)
    t = start
    while t < (end or now):
        fail(conn, kind, t, reason, diagnostic)
        t += step
    if end is not None and recover:
        ok(conn, kind, end)
    row = row_of(conn, kind)
    return CoverageWindow.objects.filter(source_key=coverage.source_key(row)).order_by('-first_failure_at').first()


def finish(w, state, backfill_state, resolved_at, **fields):
    for k, v in fields.items():
        setattr(w, k, v)
    w.state = state
    w.backfill_state = backfill_state
    w.resolved_at = resolved_at
    w.backfill_next_at = None
    # The once-per-gap notifications for these happened at the time.
    w.notified_prolonged_at = w.notified_prolonged_at or (w.first_failure_at + 30 * M)
    if state in (coverage.PARTIAL_RECOVERY, coverage.UNRECOVERABLE_GAP):
        w.notified_unrecovered_at = resolved_at
    w.save()


# --- Northwind PBS: three gaps in its history, quiet now -----------------------------------
# The backup server declares its history (7 days, a short page ends the
# results), so each recovery queued a backfill; what that backfill found is
# written here instead of being fetched.
PBS_CAP = coverage.HistoryCapability(supports_history=True, max_lookback=7 * D, ordering=coverage.ORDER_UNORDERED,
                                     pagination=coverage.PAGE_SHORT, page_size=200).as_dict()
start = now - 9 * D - 6 * H
w = outage(pbs, 'backup', start, start + 2 * H + 40 * M, 20 * M, sh.TIMEOUT,
           'Read timed out after 10 s (pbs.northwind.example:8007).')
# Two task records could not be read: alerts from this window may be missing.
finish(w, coverage.PARTIAL_RECOVERY, 'incomplete', w.recovered_at + 6 * M,
       capability=PBS_CAP, backfill_from=w.coverage_lost_at, backfill_to=w.recovered_at, pages_fetched=1,
       records_fetched=9,
       recovered_count=3, duplicate_count=4, rejected_count=2, max_delay_seconds=2 * 3600 + 25 * 60,
       backfill_attempts=1, checkpoint_at=w.recovered_at)
start = now - 6 * D - 2 * H
w = outage(pbs, 'backup', start, start + 55 * M, 15 * M, sh.ENDPOINT_UNAVAILABLE,
           'HTTP 503 from the backup server during maintenance.')
finish(w, coverage.RECOVERED_LATE, 'complete', w.recovered_at + 3 * M,
       capability=PBS_CAP, backfill_from=w.coverage_lost_at, backfill_to=w.recovered_at, pages_fetched=1,
       records_fetched=0,
       backfill_attempts=1, checkpoint_at=w.recovered_at)
start = now - 2 * D - 7 * H
w = outage(pbs, 'backup', start, start + 4 * H + 10 * M, 20 * M, sh.ENDPOINT_UNAVAILABLE,
           'Connection refused: the backup server was rebooting after an update.')
# Complete: every page read, the last one short, nothing rejected. Four
# nightly backup runs finished during the outage and were delivered late.
finish(w, coverage.RECOVERED_LATE, 'complete', w.recovered_at + 5 * M,
       capability=PBS_CAP, backfill_from=w.coverage_lost_at, backfill_to=w.recovered_at, pages_fetched=1,
       records_fetched=6,
       recovered_count=4, duplicate_count=2, rejected_count=0, max_delay_seconds=3 * 3600 + 48 * 60,
       backfill_attempts=1, checkpoint_at=w.recovered_at)
pbs_open = BackupAlert.objects.filter(connection=pbs, status__in=('open', 'acknowledged')).count()
for i in range(4, 0, -1):
    ok(pbs, 'backup', now - (i * 15 + 3) * M, open_alerts=pbs_open)

# --- Ridgeline Tactical RMM: Unrecoverable Gap 4 days ago, verified now ---------------------
start = now - 4 * D - 3 * H
w = outage(tactical, 'rmm', start, start + 2 * H + 15 * M, 15 * M, sh.AUTHENTICATION_FAILURE,
           'HTTP 401: the API key was rotated on the RMM server and not yet updated here.')
# The RMM declares no history: on_collection resolved it as unrecoverable.
finish(w, coverage.UNRECOVERABLE_GAP, 'unsupported', w.recovered_at + M)
rmm_open = RMMAlert.objects.filter(connection=tactical, status='active').count()
for i in range(3, 0, -1):
    ok(tactical, 'rmm', now - (i * 20 + 1) * M, open_alerts=rmm_open)

# --- Harbor Point NinjaOne: open Coverage Gap -------------------------------------------------
ok(ninja, 'rmm', now - 2 * D)
for i in range(16, 0, -1):
    ok(ninja, 'rmm', now - 75 * M - i * 30 * M)
outage(ninja, 'rmm', now - 70 * M, None, 10 * M, sh.ENDPOINT_UNAVAILABLE,
       'HTTP 503 Service Unavailable from ninja.harborpoint.example.')
gap = CoverageWindow.objects.get(source_key=coverage.source_key(row_of(ninja, 'rmm')), state=coverage.COVERAGE_GAP)
CoverageWindow.objects.filter(pk=gap.pk).update(notified_prolonged_at=gap.first_failure_at + 30 * M)

# --- Defender - Northwind: Partial Recovery earlier today with late alerts, active now ------
# The vendor API failed for 3 h 40 min. The first read after recovery
# returned three alerts that had happened during the outage: they are stored
# as delivered late, through the same path a poll uses (deduplication,
# alert-to-ticket rules, incident correlation). The security adapters cannot
# ask for history, so what that read returned is all there is: the window
# ends as Partial Recovery, exactly as the recording path resolves it.
start = now - 5 * H - 50 * M
outage(defender, 'security', start, start + 3 * H + 40 * M, 10 * M, sh.ENDPOINT_UNAVAILABLE,
       'HTTP 502 Bad Gateway from the vendor API.', recover=False)
w = CoverageWindow.objects.get(source_key=coverage.source_key(row_of(defender, 'security')),
                               state=coverage.COVERAGE_GAP)
received = start + 3 * H + 40 * M
LATE = [
    # external id, severity, title, asset, minutes after coverage was lost, description
    ('demo-late-1', 'high', 'Credential dumping tool blocked on a file server', 'NWL-FS01', 18,
     'A process reading LSASS memory was blocked; it was launched from a scheduled task created the same hour.'),
    ('demo-late-2', 'medium', 'PowerShell download cradle run by a signed-in user', 'NWL-WS14', 111,
     'An encoded PowerShell command fetched a script from an unknown host. The script did not run again.'),
    ('demo-late-3', 'low', 'New local administrator account created', 'NWL-WS14', 196,
     'Local account "support2" was added to the Administrators group on the workstation.'),
]
late_ids, delays = [], []
for ext, sev, title, asset, minutes, desc in LATE:
    occurred = w.coverage_lost_at + minutes * M
    out = ingest_polled_alert(defender, {
        'external_id': ext, 'severity': sev, 'title': title, 'description': desc, 'asset_hint': asset,
        'occurred_at': occurred.isoformat(), 'raw_payload': {'demo': True}}, window=w)
    a = out['alert']
    late_ids.append(a.pk)
    # Received during the first read after recovery, not when this script ran.
    seen = received + timedelta(seconds=5 * len(late_ids))
    delay = int((seen - occurred).total_seconds())
    delays.append(delay)
    SecurityAlert.objects.filter(pk=a.pk).update(
        seen_at=seen, delivery_delay_seconds=delay, status='acknowledged' if sev == 'low' else 'new')
    a.refresh_from_db()
    for inc in SecurityIncident.objects.filter(alerts__pk=a.pk):
        SecurityIncident.objects.filter(pk=inc.pk).update(opened_at=seen)
        ev = inc.events.filter(kind='delivered_late').first()
        if ev is not None:
            ev.message = late_note(a)
            ev.save(update_fields=['message'])
        inc.events.all().update(occurred_at=seen)
coverage.note_delivered(w, late=len(late_ids), max_delay=max(delays))
ok(defender, 'security', received, open_alerts=len(late_ids), retrieved=len(late_ids))
w.refresh_from_db()
CoverageWindow.objects.filter(pk=w.pk).update(
    resolved_at=received, notified_prolonged_at=w.first_failure_at + 60 * M, notified_unrecovered_at=received)
open_sec = SecurityAlert.objects.filter(connection=defender, status__in=('new', 'acknowledged')).count()
for i in range(4, 0, -1):
    ok(defender, 'security', now - (i * 10 + 2) * M, open_alerts=open_sec)
# The "Security & Alerts" starter wallboard, made from its template as the
# wallboard editor does; its last widget is the monitoring coverage table.
from django.contrib.auth.models import User
from reports.models import Wallboard, WallboardWidget
from reports.widget_sources import get_template
board = Wallboard.objects.filter(organization__isnull=True, name='Security & Alerts').first()
if board is None:
    board = Wallboard.objects.create(organization=None, name='Security & Alerts', refresh_seconds=60, order=20,
                                     description='Critical alerts and whether every source is being watched.',
                                     created_by=User.objects.get(username='demo.tech'))
    # Arranged as an editor would for the office screen: the four counters
    # in a row, then the coverage table across the full width so all of its
    # columns show, then the open alerts by severity.
    layout = {'security_alerts_open_critical': (10, 3), 'security_alerts_24h': (20, 3),
              'recent_failed_logins': (30, 3), 'vault_activity_24h': (40, 3),
              'monitoring_coverage': (50, 12), 'alerts_by_severity': (60, 4)}
    for wdg in get_template('alerts')['widgets']:
        order, width = layout.get(wdg['data_source'], (70, 4))
        WallboardWidget.objects.create(wallboard=board, title=wdg['title'][:200], widget_type=wdg['widget_type'],
                                       data_source=wdg['data_source'], order=order, position={'width': width})

print('coverage demo data ready:', CoverageWindow.objects.count(), 'windows,', len(late_ids), 'late alerts')
