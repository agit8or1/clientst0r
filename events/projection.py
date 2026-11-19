"""Projection engine: source rows → OperationalEvent (+ EventLink rows).

Runs only from the scheduler (``events_tick``), never inside a web request,
with a time budget per run so a slow or failing source cannot pile up work or
slow the Service Desk.
"""
import logging
import time
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import models as M
from .sources import ADAPTERS

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5          # then the queue item becomes a dead letter
DRAIN_BATCH = 500
SCAN_BATCH = 500          # new rows per source per run (backfill pace)
RECHECK_BATCH = 200       # live events revisited per run
DEAD_LETTER_DAYS = 30


def project(source, source_id):
    """Create, update or close the event for one source row. Returns the
    event, or None when the source row is gone (its event is then closed)."""
    adapter = ADAPTERS[source]
    if source == M.SOURCE_MONITOR:
        return _project_monitor(adapter, source_id)
    obj = adapter.load(source_id)
    if obj is None:
        _close_orphans(source, source_id)
        return None
    data = adapter.envelope(obj)
    tickets, incidents = adapter.links(obj)
    with transaction.atomic():
        event = _upsert(source, source_id, data)
        _sync_links(event, tickets, incidents)
    return event


def _upsert(source, source_id, data):
    data = dict(data)
    dedup_key = data.pop('dedup_key')
    data['projected_at'] = timezone.now()
    data['source_id'] = source_id
    try:
        with transaction.atomic():
            event, _ = M.OperationalEvent.objects.update_or_create(source=source, dedup_key=dedup_key,
                                                                    defaults=data)
    except IntegrityError:  # a concurrent run created it first
        event = M.OperationalEvent.objects.get(source=source, dedup_key=dedup_key)
        for k, v in data.items():
            setattr(event, k, v)
        event.save()
    return event


def _sync_links(event, tickets, incidents):
    """Make the source-recorded links match the source; links a person made
    stay as they are."""
    existing = list(event.links.filter(origin=M.EventLink.ORIGIN_SOURCE))
    have_t = {l.ticket_id for l in existing if l.ticket_id}
    have_i = {l.incident_id for l in existing if l.incident_id}
    stale = [l.pk for l in existing if (l.ticket_id and l.ticket_id not in tickets)
             or (l.incident_id and l.incident_id not in incidents)]
    if stale:
        M.EventLink.objects.filter(pk__in=stale).delete()
    manual_t = set(event.links.filter(origin=M.EventLink.ORIGIN_MANUAL, ticket__isnull=False)
                   .values_list('ticket_id', flat=True))
    manual_i = set(event.links.filter(origin=M.EventLink.ORIGIN_MANUAL, incident__isnull=False)
                   .values_list('incident_id', flat=True))
    new = [M.EventLink(event=event, ticket_id=t) for t in tickets - have_t - manual_t]
    new += [M.EventLink(event=event, incident_id=i) for i in incidents - have_i - manual_i]
    if new:
        M.EventLink.objects.bulk_create(new, ignore_conflicts=True)


def _close_orphans(source, source_id):
    M.OperationalEvent.objects.filter(source=source, source_id=source_id,
                                      status__in=(M.STATUS_OPEN, M.STATUS_ACK)).update(
        status=M.STATUS_RESOLVED, source_status='deleted', resolved_at=timezone.now(),
        projected_at=timezone.now())


def _project_monitor(adapter, monitor_id):
    monitor = adapter.load(monitor_id)
    live = (M.OperationalEvent.objects.filter(source=M.SOURCE_MONITOR, source_id=monitor_id,
                                              status__in=(M.STATUS_OPEN, M.STATUS_ACK))
            .order_by('-first_seen_at').first())
    now = timezone.now()
    if monitor is None or monitor.alert_state != 'down' or not monitor.is_enabled:
        if live is not None:
            live.status = M.STATUS_RESOLVED
            live.source_status = 'deleted' if monitor is None else ('disabled' if not monitor.is_enabled else 'up')
            live.resolved_at = now
            live.last_seen_at = now
            live.projected_at = now
            live.save()
        return live
    if live is None:
        started = now
        data = {'first_seen_at': started, 'dedup_key': f'monitor:{monitor.pk}:{int(started.timestamp())}'}
    else:
        data = {'first_seen_at': live.first_seen_at, 'dedup_key': live.dedup_key}
    data.update({
        'organization_id': monitor.organization_id,
        'connection_label': monitor.name[:160],
        'vendor_event_id': '',
        'event_type': 'website down',
        'title': f'{monitor.name} is down'[:300],
        'severity': 'high',
        'source_severity': monitor.status,
        'status': live.status if live else M.STATUS_OPEN,
        'source_status': 'down',
        'last_seen_at': monitor.last_checked_at or now,
        'resolved_at': None,
        'occurrences': max(monitor.consecutive_failures, 1),
        'asset_hint': monitor.url[:200],
        'raw': {'url': monitor.url, 'status_code': monitor.last_status_code,
                'error': (monitor.last_error or '')[:1000]},
        'correlation_group': '',
    })
    return _upsert(M.SOURCE_MONITOR, monitor.pk, data)


# --------------------------------------------------------------------------
# Scheduler passes
# --------------------------------------------------------------------------

class _Health:
    """Per-source counters for one run, written to SourceHealth at the end."""

    def __init__(self):
        self.ok, self.errors = {}, {}

    def success(self, source):
        self.ok[source] = self.ok.get(source, 0) + 1

    def failure(self, source, message):
        self.errors[source] = message[:500]

    def save(self, started, duration_ms, watermarks):
        now = timezone.now()
        for source in ADAPTERS:
            h, _ = M.SourceHealth.objects.get_or_create(source=source)
            h.last_run_at = now
            h.last_duration_ms = duration_ms
            h.last_batch = self.ok.get(source, 0)
            h.total_projected += self.ok.get(source, 0)
            if source in watermarks:
                h.scan_watermark = watermarks[source]
            if source in self.errors:
                h.consecutive_failures += 1
                h.last_error, h.last_error_at = self.errors[source], now
            else:
                h.consecutive_failures = 0
                h.last_success_at = now
            h.save()


def run(budget_seconds=40):
    """One scheduler run: drain the queue, scan for new rows, recheck live
    events, apply retention. Returns a summary dict."""
    settings = M.EventSettings.get()
    summary = {'drained': 0, 'failed': 0, 'scanned': 0, 'rechecked': 0, 'pruned': 0}
    if not settings.ingestion_enabled:
        summary['disabled'] = True
        return summary
    started = time.monotonic()
    deadline = started + budget_seconds
    health = _Health()
    watermarks = {}
    summary['drained'], summary['failed'] = _drain(health, deadline)
    if time.monotonic() < deadline:
        summary['scanned'] = _scan(health, watermarks, deadline)
    if time.monotonic() < deadline:
        summary['rechecked'] = _recheck(health, deadline)
    summary['pruned'] = prune(settings)
    health.save(started, int((time.monotonic() - started) * 1000), watermarks)
    return summary


def _attempt(health, source, source_id):
    try:
        project(source, source_id)
    except Exception as exc:  # noqa: BLE001 — recorded, retried, then dead-lettered
        logger.warning('events: projecting %s %s failed', source, source_id, exc_info=True)
        health.failure(source, f'{type(exc).__name__}: {exc}')
        return f'{type(exc).__name__}: {exc}'
    health.success(source)
    return None


def _drain(health, deadline):
    done = failed = 0
    items = list(M.ProjectionQueueItem.objects.filter(dead=False).order_by('queued_at')[:DRAIN_BATCH])
    for item in items:
        if time.monotonic() >= deadline:
            break
        if item.source not in ADAPTERS:
            item.delete()
            continue
        error = _attempt(health, item.source, item.source_id)
        if error is None:
            item.delete()
            done += 1
            continue
        failed += 1
        item.attempts += 1
        item.last_error = error[:300]
        item.dead = item.attempts >= MAX_ATTEMPTS
        item.save(update_fields=['attempts', 'last_error', 'dead'])
    return done, failed


def _scan(health, watermarks, deadline):
    """Rows created without a save signal (bulk inserts, first run backfill)."""
    count = 0
    for source, adapter in ADAPTERS.items():
        if time.monotonic() >= deadline:
            break
        if source == M.SOURCE_MONITOR:
            count += _scan_monitors(health, deadline)
            continue
        h = M.SourceHealth.objects.filter(source=source).first()
        mark = h.scan_watermark if h else 0
        try:
            pks = adapter.new_rows(mark, SCAN_BATCH)
        except Exception as exc:  # noqa: BLE001
            health.failure(source, f'scan: {type(exc).__name__}: {exc}')
            continue
        for pk in pks:
            if time.monotonic() >= deadline:
                break
            if _attempt(health, source, pk) is not None:
                # Queue the failed row so retries and dead-lettering apply;
                # the watermark can then move past it.
                M.ProjectionQueueItem.objects.bulk_create(
                    [M.ProjectionQueueItem(source=source, source_id=pk)], ignore_conflicts=True)
            mark = pk
            count += 1
        watermarks[source] = mark
    return count


def _scan_monitors(health, deadline):
    from monitoring.models import WebsiteMonitor
    live = M.OperationalEvent.objects.filter(source=M.SOURCE_MONITOR,
                                             status__in=(M.STATUS_OPEN, M.STATUS_ACK)).values('source_id')
    down = WebsiteMonitor.objects.filter(alert_state='down', is_enabled=True).exclude(pk__in=live)
    count = 0
    for pk in down.values_list('pk', flat=True)[:SCAN_BATCH]:
        if time.monotonic() >= deadline:
            break
        _attempt(health, M.SOURCE_MONITOR, pk)
        count += 1
    return count


def _recheck(health, deadline):
    """Revisit the live events projected longest ago, so changes made with
    bulk updates (no save signal) still arrive."""
    count = 0
    rows = (M.OperationalEvent.objects.filter(status__in=(M.STATUS_OPEN, M.STATUS_ACK))
            .order_by('projected_at').values_list('source', 'source_id')[:RECHECK_BATCH])
    seen = set()
    for source, source_id in rows:
        if time.monotonic() >= deadline:
            break
        if (source, source_id) in seen or source not in ADAPTERS:
            continue
        seen.add((source, source_id))
        _attempt(health, source, source_id)
        count += 1
    return count


def prune(settings=None):
    """Retention and quota (82.4): closed events past retention, raw copies
    past raw retention, the oldest closed events beyond the quota, and old
    dead letters. Live events are never pruned."""
    settings = settings or M.EventSettings.get()
    now = timezone.now()
    closed = M.OperationalEvent.objects.exclude(status__in=(M.STATUS_OPEN, M.STATUS_ACK))
    deleted = 0
    # Precedence: customer, then source, then install-wide. 0 keeps forever.
    customers = dict(M.CustomerRetention.objects.values_list('organization_id', 'retention_days'))
    for org_id, days in customers.items():
        if days:
            deleted += closed.filter(organization_id=org_id,
                                     last_seen_at__lt=now - timedelta(days=days)).delete()[0]
    rest = closed.exclude(organization_id__in=list(customers))
    sources = {k: v for k, v in (settings.source_retention_days or {}).items() if k in dict(M.SOURCES)}
    for source, days in sources.items():
        if days:
            deleted += rest.filter(source=source, last_seen_at__lt=now - timedelta(days=int(days))).delete()[0]
    if settings.retention_days:
        deleted += rest.exclude(source__in=list(sources)).filter(
            last_seen_at__lt=now - timedelta(days=settings.retention_days)).delete()[0]
    if settings.raw_retention_days:
        (M.OperationalEvent.objects.filter(last_seen_at__lt=now - timedelta(days=settings.raw_retention_days))
         .exclude(raw={}).update(raw={}))
    if settings.max_events:
        over = M.OperationalEvent.objects.count() - settings.max_events
        if over > 0:
            ids = list(closed.order_by('last_seen_at').values_list('pk', flat=True)[:min(over, 5000)])
            deleted += M.OperationalEvent.objects.filter(pk__in=ids).delete()[0]
    M.ProjectionQueueItem.objects.filter(dead=True, queued_at__lt=now - timedelta(days=DEAD_LETTER_DAYS)).delete()
    return deleted


def retry_dead_letters():
    return M.ProjectionQueueItem.objects.filter(dead=True).update(dead=False, attempts=0, last_error='')
