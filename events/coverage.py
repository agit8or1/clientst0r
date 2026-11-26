"""Monitoring coverage: gaps, recovery and backfill (roadmap 82.15–82.20).

Community feedback (GitHub Discussion #161): a source that recovers after
several failed reads and backfills the missed window must not look like a
quiet one. Analysts need to know which alerts were not seen in real time.

What this module adds on top of the health contract (events.source_health):

* A ``CoverageWindow`` per interruption, per source and customer. It records
  failed reads, outage start, recovery time, the last verified coverage
  before the outage, and how the missed window was resolved. Windows are
  history: a later outage opens a new one.
* Declared history capabilities per provider (``HistoryCapability``). A
  window counts as fully recovered only when the provider declares
  everything needed (history support, a maximum lookback, its ordering and a
  pagination completeness signal) *and* the retrieval proved the end of the
  results. A 200 response alone proves nothing; an undeclared capability is
  never complete.
* A scheduler-driven backfill (``backfill_tick``, from events_tick) with
  durable checkpoints (page token in the database, saved after every page),
  bounded pages and attempts, retry backoff and a lookback cap. It never runs
  on page render. Records go through the normal ingest path, so their
  deduplication keys, alert-to-ticket rules, incident correlation and
  playbook approvals apply unchanged; they are only marked delivered late.
* Six states (``COVERAGE``): Verified Quiet, Active Monitoring, Coverage Gap,
  Recovered – Delivered Late, Partial Recovery and Unrecoverable Gap, plus
  "Not verified" for a source whose coverage cannot be established at all.
* Notifications through the existing technician e-mail, once per gap: when
  an interruption lasts longer than the configured threshold, and when a
  gap could not be fully recovered.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import timedelta
from typing import Optional

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from . import source_health as sh

logger = logging.getLogger('events.coverage')

# --- states -----------------------------------------------------------------------------------

VERIFIED_QUIET = 'verified_quiet'
ACTIVE_MONITORING = 'active_monitoring'
COVERAGE_GAP = 'coverage_gap'
RECOVERED_LATE = 'recovered_late'
PARTIAL_RECOVERY = 'partial_recovery'
UNRECOVERABLE_GAP = 'unrecoverable_gap'
NOT_VERIFIED = 'not_verified'
COVERAGE_VALUES = (VERIFIED_QUIET, ACTIVE_MONITORING, COVERAGE_GAP, RECOVERED_LATE, PARTIAL_RECOVERY,
                   UNRECOVERABLE_GAP, NOT_VERIFIED)
WINDOW_VALUES = (COVERAGE_GAP, RECOVERED_LATE, PARTIAL_RECOVERY, UNRECOVERABLE_GAP)

COVERAGE = {
    # key: (label, Bootstrap colour, icon, rank — higher is worse, tooltip)
    VERIFIED_QUIET: ('Verified Quiet', 'success', 'fa-circle-check', 0,
                     'Collection verified and uninterrupted; no qualifying alerts.'),
    ACTIVE_MONITORING: ('Active Monitoring', 'primary', 'fa-satellite-dish', 1,
                        'Collection verified and uninterrupted; alerts are arriving in real time.'),
    RECOVERED_LATE: ('Recovered – Delivered Late', 'info', 'fa-clock-rotate-left', 2,
                     'The source was interrupted. The missed window was retrieved completely afterwards; the '
                     'events in it were not seen in real time.'),
    NOT_VERIFIED: ('Not Verified', 'secondary', 'fa-circle-question', 3,
                   'Coverage cannot be established for this source (for example a push-only source).'),
    PARTIAL_RECOVERY: ('Partial Recovery', 'warning', 'fa-circle-half-stroke', 4,
                       'The source was interrupted and only part of the missed window could be retrieved, or '
                       'completeness could not be proven. Alerts from the gap may be missing.'),
    COVERAGE_GAP: ('Coverage Gap', 'danger', 'fa-link-slash', 5,
                   'The source is interrupted, or its missed window has not been recovered yet. Alerts from '
                   'this period have not been seen.'),
    UNRECOVERABLE_GAP: ('Unrecoverable Gap', 'danger', 'fa-ban', 6,
                        'The source was interrupted and the missed window cannot be retrieved. Alerts from the '
                        'gap may be missing permanently.'),
}


@dataclass(frozen=True)
class CoverageDisplay:
    key: str
    label: str
    badge: str
    icon: str
    rank: int
    tooltip: str


def coverage_display(key: str, *, recovered: Optional[int] = None) -> CoverageDisplay:
    key = key if key in COVERAGE else NOT_VERIFIED
    label, badge, icon, rank, tip = COVERAGE[key]
    if key == RECOVERED_LATE and recovered == 0:
        label = 'Recovered – None Missed'
        tip = ('The source was interrupted. The missed window was retrieved completely afterwards and held no '
               'events. The interruption stays on record.')
    elif key == RECOVERED_LATE and recovered:
        tip += f' {recovered} event{"s" if recovered != 1 else ""} delivered late.'
    return CoverageDisplay(key, label, badge, icon, rank, tip)


# --- capabilities -----------------------------------------------------------------------------

ORDER_ASCENDING, ORDER_DESCENDING, ORDER_UNORDERED = 'ascending', 'descending', 'unordered'
ORDERINGS = (ORDER_ASCENDING, ORDER_DESCENDING, ORDER_UNORDERED)
PAGE_CURSOR, PAGE_SHORT, PAGE_TOTAL, PAGE_NONE = 'cursor_exhausted', 'short_page', 'total_count', 'none'
PAGINATION_SIGNALS = (PAGE_CURSOR, PAGE_SHORT, PAGE_TOTAL, PAGE_NONE)
PROVING_SIGNALS = (PAGE_CURSOR, PAGE_SHORT, PAGE_TOTAL)


@dataclass(frozen=True)
class HistoryCapability:
    """What a provider declares about retrieving past events. ``None`` in any
    field means "not declared", and an undeclared capability never makes a
    window complete.

    supports_history  True: events can be asked for by time window.
    max_lookback      How far back the provider keeps and returns events.
    ordering          ascending | descending | unordered (results are not
                      time-ordered: Clientst0r validates every timestamp).
    pagination        How the provider says the results are exhausted:
                      cursor_exhausted (no next cursor and an explicit end),
                      short_page (a page shorter than the limit), total_count
                      (a total to count against), none (no signal).
    page_size         Records asked for per page.
    """
    supports_history: Optional[bool] = None
    max_lookback: Optional[timedelta] = None
    ordering: Optional[str] = None
    pagination: Optional[str] = None
    page_size: int = 100

    def can_prove_complete(self) -> bool:
        return (self.supports_history is True and self.max_lookback is not None and self.max_lookback > timedelta(0)
                and self.ordering in ORDERINGS and self.pagination in PROVING_SIGNALS)

    def as_dict(self) -> dict:
        return {'supports_history': self.supports_history,
                'max_lookback_minutes': int(self.max_lookback.total_seconds() // 60) if self.max_lookback else None,
                'ordering': self.ordering, 'pagination': self.pagination}


UNDECLARED = HistoryCapability()
NO_HISTORY = HistoryCapability(supports_history=False)


@dataclass
class HistoryPage:
    """One page of past events from a provider."""
    records: list = field(default_factory=list)
    next_token: str = ''                # where the next page starts ('' = none offered)
    exhausted: Optional[bool] = None    # the provider said explicitly that nothing follows
    total: Optional[int] = None         # total results for the window, when the provider gives one
    raw_count: Optional[int] = None     # results the provider returned, when some were not records


def page_end(cap: HistoryCapability, page: HistoryPage, fetched_total: int, limit: int) -> tuple:
    """('more', token) or ('end', proven). ``proven`` is True only when the
    provider's declared completeness signal says the results are exhausted."""
    count = page.raw_count if page.raw_count is not None else len(page.records)
    token = str(page.next_token or '')
    if cap.pagination == PAGE_CURSOR:
        if token:
            return 'more', token
        return 'end', page.exhausted is True
    if cap.pagination == PAGE_SHORT:
        if count < limit:
            return 'end', True
        return ('more', token) if token else ('end', False)
    if cap.pagination == PAGE_TOTAL:
        if page.total is not None and fetched_total >= page.total:
            return 'end', True
        return ('more', token) if token else ('end', False)
    return ('more', token) if token else ('end', False)


def resolve(cap: HistoryCapability, *, proven_end: bool, truncated: bool, rejected: int, recovered: int,
            covered_any: bool) -> tuple:
    """(window state, backfill state) at the end of a backfill. Complete
    only when the capability can prove it AND the retrieval proved it."""
    if proven_end and cap.can_prove_complete() and not truncated and not rejected:
        return RECOVERED_LATE, 'complete'
    if covered_any or recovered:
        return PARTIAL_RECOVERY, 'incomplete'
    return UNRECOVERABLE_GAP, 'incomplete'


def resolve_without_history(cap: HistoryCapability, recovered: int) -> tuple:
    """A source that cannot (or does not declare it can) return past events:
    what the first read after recovery delivered is all there is."""
    return (PARTIAL_RECOVERY if recovered else UNRECOVERABLE_GAP), 'unsupported'


def valid_event_time(value, now):
    dt = sh._parse_time(value)
    if dt is None or not (sh.EARLIEST_PLAUSIBLE <= dt <= now + sh.MAX_FUTURE_SKEW):
        return None
    return dt


def is_late(window, occurred, ingested, *, via_backfill=False) -> bool:
    """An event stored while a gap is open was not seen in real time when it
    happened inside the gap (or, with no trustworthy time, when it came from
    the backfill or from the first read after recovery)."""
    if window is None:
        return False
    if occurred is None:
        return via_backfill or window.recovered_at is None
    end = window.recovered_at or ingested
    return window.coverage_lost_at <= occurred < end


def delay_seconds(occurred, ingested) -> Optional[int]:
    if occurred is None or ingested is None:
        return None
    return max(0, int((ingested - occurred).total_seconds()))


def format_delay(seconds) -> str:
    if seconds is None or seconds == '':
        return 'unknown'
    seconds = int(seconds)
    if seconds < 120:
        return f'{seconds} s'
    if seconds < 7200:
        return f'{seconds // 60} min'
    if seconds < 2 * 86400:
        return f'{seconds // 3600} h {seconds % 3600 // 60} min'
    return f'{seconds // 86400} d {seconds % 86400 // 3600} h'


# --- backfill adapters ------------------------------------------------------------------------

class BackfillAdapter:
    """Connects one kind of monitoring source to the backfill. ``fetch``
    returns a HistoryPage; ``ingest`` stores one record through the source's
    normal path and returns (created, rejected, late, delay_seconds)."""
    kind = ''

    def __init__(self, conn):
        self.conn = conn

    @property
    def capability(self) -> HistoryCapability:
        return UNDECLARED

    def can_fetch(self) -> bool:
        return False

    def fetch(self, start, end, token, limit) -> HistoryPage:
        raise NotImplementedError

    def ingest(self, record, window, now):
        raise NotImplementedError


class SecurityBackfill(BackfillAdapter):
    """Polled security connectors (security_alerts.adapters). A provider opts
    in by declaring ``history_capability`` and implementing
    ``fetch_history``; none of the shipped adapters does yet (82.14)."""
    kind = 'security'

    def __init__(self, conn):
        super().__init__(conn)
        from security_alerts.capabilities import api_adapter
        self.provider = api_adapter(conn.provider)

    @property
    def capability(self):
        cap = getattr(self.provider, 'history_capability', None) if self.provider else None
        return cap if isinstance(cap, HistoryCapability) else UNDECLARED

    def can_fetch(self):
        from security_alerts.adapters.base import SecurityProvider
        return (self.provider is not None and self.capability.supports_history is True
                and type(self.provider).fetch_history is not SecurityProvider.fetch_history)

    def fetch(self, start, end, token, limit):
        page = self.provider.fetch_history(self.conn, start, end, page_token=token or None, limit=limit)
        if not isinstance(page, HistoryPage):
            raise _InvalidPage('The adapter returned no history page.')
        return page

    def ingest(self, record, window, now):
        from security_alerts.adapters.base import ingest_polled_alert
        if not isinstance(record, dict):
            raise _InvalidPage('record is not an object')
        out = ingest_polled_alert(self.conn, record, window=window, via_backfill=True)
        return out['created'], False, out['late'], out['delay']


class BackupBackfill(BackfillAdapter):
    """Polled backup connections: backup runs, deduplicated by the provider's
    run id (record_run). Push providers have no history to ask for."""
    kind = 'backup'

    def __init__(self, conn):
        super().__init__(conn)
        from backup_monitoring.providers import get_backup_provider
        try:
            self.provider = get_backup_provider(conn)
        except Exception:
            self.provider = None

    @property
    def capability(self):
        if self.provider is None:
            return UNDECLARED
        if getattr(self.provider, 'push', False):
            return NO_HISTORY
        cap = getattr(self.provider, 'history_capability', None)
        return cap if isinstance(cap, HistoryCapability) else UNDECLARED

    def can_fetch(self):
        return (self.provider is not None and self.capability.supports_history is True
                and callable(getattr(self.provider, 'fetch_history', None)))

    def fetch(self, start, end, token, limit):
        page = self.provider.fetch_history(start, end, token or None, limit)
        if not isinstance(page, HistoryPage):
            raise _InvalidPage('The provider returned no history page.')
        return page

    def ingest(self, run, window, now):
        from backup_monitoring.recording import ensure_job, record_run
        job = ensure_job(self.conn, run.job_external_id, run.job_name or run.job_external_id,
                         run.system_external_id, run.system_name)
        _, outcome = record_run(job, run.external_id, run.started_at, run.status, run.finished_at,
                                run.bytes_processed, run.message)
        occurred = run.finished_at or run.started_at
        created = outcome == 'created'
        late = created and is_late(window, occurred, now, via_backfill=True)
        return created, False, late, delay_seconds(occurred, now) if late else None


class RMMBackfill(BackfillAdapter):
    """RMM sync reads the current alert list: alerts still active at recovery
    are collected again, alerts that started and cleared during the gap are
    not available. Declared as no history."""
    kind = 'rmm'

    @property
    def capability(self):
        return NO_HISTORY


ADAPTERS = {'security': SecurityBackfill, 'backup': BackupBackfill, 'rmm': RMMBackfill}


def adapter_for(row):
    cls = ADAPTERS.get(row.kind)
    conn = row.connection if row is not None else None
    if cls is None or conn is None:
        return None
    try:
        return cls(conn)
    except Exception:
        logger.warning('coverage: no backfill adapter for %s', row, exc_info=True)
        return None


class _InvalidPage(ValueError):
    health_reason = 'invalid_response'


# --- recording (called inside record_collection's transaction) -------------------------------

def source_key(row) -> str:
    return f'{row.kind}:{row.content_type_id}:{row.object_id}'


def open_window(conn, kind):
    """The open (unresolved) window of a connection's source, or None."""
    from django.contrib.contenttypes.models import ContentType
    from .models import CoverageWindow
    try:
        ct = ContentType.objects.get_for_model(type(conn))
        return CoverageWindow.objects.filter(source_key=f'{kind}:{ct.pk}:{conn.pk}', state=COVERAGE_GAP).first()
    except Exception:
        logger.warning('coverage: could not read the open window', exc_info=True)
        return None


def _open(row, *, at, cause, name='', coverage_lost_at=None):
    from .models import CoverageWindow
    lost = coverage_lost_at or row.window_end_complete or row.last_success_at or at
    try:
        with transaction.atomic():
            return CoverageWindow.objects.create(
                organization_id=row.organization_id, health=row, source_key=source_key(row), kind=row.kind,
                source_name=(name or '')[:200], state=COVERAGE_GAP, cause=(cause or '')[:30],
                coverage_lost_at=min(lost, at), first_failure_at=at, last_failure_at=at, failed_reads=1)
    except IntegrityError:      # another worker opened it
        return CoverageWindow.objects.filter(source_key=source_key(row), state=COVERAGE_GAP).first()


def on_collection(row, f, attempted_at, *, name='', previous_cursor=None):
    """Update coverage for one recorded attempt. ``f`` is the evaluated
    record (events.source_health.evaluate). Never raises."""
    from .models import CoverageWindow
    try:
        with transaction.atomic():
            window = (CoverageWindow.objects.select_for_update()
                      .filter(source_key=source_key(row), state=COVERAGE_GAP).first())
            if f['outcome'] == sh.FAILED:
                if window is None:
                    return _open(row, at=attempted_at, cause=f.get('reason') or sh.OTHER, name=name,
                                 coverage_lost_at=previous_cursor)
                window.failed_reads += 1
                window.last_failure_at = attempted_at
                if window.recovered_at is not None:
                    # Failed again before the missed window was recovered:
                    # one longer gap, resumed from the same checkpoint.
                    window.recovered_at = None
                    window.backfill_state = ''
                    window.backfill_next_at = None
                window.save()
                return window
            if f['outcome'] in (sh.SUCCESS, sh.PARTIAL) and window is not None and window.recovered_at is None:
                window.recovered_at = attempted_at
                window.backfill_to = attempted_at
                window.save()
                _start_recovery(window, row)
            return window
    except Exception:
        logger.warning('coverage: could not record the attempt for %s', row.pk, exc_info=True)
        return None


def _start_recovery(window, row, now=None):
    """Decide how the missed window is recovered: queue a backfill, or
    resolve it now when the source cannot be asked for history."""
    from .models import EventSettings
    now = now or timezone.now()
    adapter = adapter_for(row)
    cap = adapter.capability if adapter else UNDECLARED
    window.capability = cap.as_dict()
    if adapter is not None and adapter.can_fetch():
        if not EventSettings.get().backfill_enabled:
            state, _ = resolve_without_history(cap, window.recovered_count)
            _finish(window, state, 'disabled', now)
            return
        window.backfill_state = 'pending'
        window.backfill_next_at = now
        window.save()
        return
    state, bstate = resolve_without_history(cap, window.recovered_count)
    _finish(window, state, bstate, now)


def _finish(window, state, backfill_state, now):
    window.state = state
    window.backfill_state = backfill_state
    window.resolved_at = now
    window.backfill_next_at = None
    window.save()
    _audit_resolution(window)


def note_delivered(window, *, late=0, duplicates=0, rejected=0, max_delay=None):
    """Add what a read delivered into an open window (atomic increments)."""
    from django.db.models import F
    from .models import CoverageWindow
    if window is None or not (late or duplicates or rejected or max_delay is not None):
        return
    try:
        CoverageWindow.objects.filter(pk=window.pk).update(
            recovered_count=F('recovered_count') + late, duplicate_count=F('duplicate_count') + duplicates,
            rejected_count=F('rejected_count') + rejected)
        if max_delay is not None:
            CoverageWindow.objects.filter(pk=window.pk).filter(
                Q(max_delay_seconds__isnull=True) | Q(max_delay_seconds__lt=max_delay)).update(
                max_delay_seconds=max_delay)
    except Exception:
        logger.warning('coverage: could not count delivered events', exc_info=True)


def open_for_stale(row, f, now):
    """Freshness sweep: a collector that stopped writing has a gap too."""
    from .models import CoverageWindow
    if CoverageWindow.objects.filter(source_key=source_key(row), state=COVERAGE_GAP).exists():
        return None
    threshold = timedelta(minutes=sh.stale_minutes(row.stale_after_minutes))
    start = (row.last_success_at + threshold) if row.last_success_at else now
    return _open(row, at=min(start, now), cause=sh.STALE_DATA, name=f.get('name', ''))


# --- backfill (scheduler only) ----------------------------------------------------------------

MAX_PAGES_PER_RUN = 20
MAX_ATTEMPTS = 6
BACKFILL_BUDGET_SECONDS = 20


def backfill_tick(now=None, budget_seconds=BACKFILL_BUDGET_SECONDS) -> dict:
    """Work through due backfills within a time budget. Each page commits its
    records and the checkpoint together, so a restart resumes at the next
    page; a page fetched twice only finds duplicates."""
    from .models import CoverageWindow, EventSettings
    now = now or timezone.now()
    deadline = time.monotonic() + budget_seconds
    summary = {'windows': 0, 'pages': 0, 'resolved': 0}
    settings = EventSettings.get()
    due = list(CoverageWindow.objects.filter(state=COVERAGE_GAP, backfill_state__in=('pending', 'running'))
               .filter(Q(backfill_next_at__isnull=True) | Q(backfill_next_at__lte=now))
               .select_related('health').order_by('backfill_next_at', 'pk')[:50])
    for window in due:
        if time.monotonic() >= deadline:
            break
        summary['windows'] += 1
        try:
            pages, resolved = _backfill_window(window, settings, now, deadline)
        except Exception:
            logger.exception('coverage: backfill of window %s failed', window.pk)
            continue
        summary['pages'] += pages
        summary['resolved'] += resolved
    return summary


def _backfill_window(window, settings, now, deadline):
    row = window.health
    adapter = adapter_for(row) if row is not None else None
    if adapter is None or not adapter.can_fetch():
        cap = adapter.capability if adapter else UNDECLARED
        window.capability = cap.as_dict()
        state, bstate = resolve_without_history(cap, window.recovered_count)
        _finish(window, state, bstate, now)
        return 0, 1
    if not settings.backfill_enabled:
        state, _ = resolve_without_history(adapter.capability, window.recovered_count)
        _finish(window, state, 'disabled', now)
        return 0, 1
    cap = adapter.capability
    window.capability = cap.as_dict()
    end = window.backfill_to or window.recovered_at or now
    cap_lookback = min(cap.max_lookback or timedelta(hours=settings.backfill_max_lookback_hours),
                       timedelta(hours=max(1, settings.backfill_max_lookback_hours)))
    start = max(window.coverage_lost_at, now - cap_lookback)
    window.lookback_truncated = start > window.coverage_lost_at
    window.backfill_from = start
    window.backfill_state = 'running'
    limit = max(1, int(cap.page_size or 100))
    pages = 0
    while pages < MAX_PAGES_PER_RUN and time.monotonic() < deadline:
        try:
            page = adapter.fetch(start, end, window.checkpoint_cursor, limit)
        except Exception as exc:
            window.backfill_attempts += 1
            window.backfill_error = f'{type(exc).__name__}: {sh.classify_exception(exc)[0]}'[:300]
            if window.backfill_attempts >= MAX_ATTEMPTS:
                state, bstate = resolve(cap, proven_end=False, truncated=window.lookback_truncated,
                                        rejected=window.rejected_count, recovered=window.recovered_count,
                                        covered_any=window.pages_fetched > 0)
                _finish(window, state, 'failed', now)
                return pages, 1
            delay = sh.next_retry_delay(window.backfill_attempts, sh.classify_exception(exc)[1])
            window.backfill_next_at = now + timedelta(seconds=delay)
            window.save()
            return pages, 0
        late = dup = rejected = 0
        max_delay = None
        newest = None
        ingested_at = timezone.now()
        with transaction.atomic():
            for rec in page.records or []:
                created, bad, was_late, delay = _ingest_one(adapter, rec, window, ingested_at)
                if bad:
                    rejected += 1
                elif created:
                    late += was_late
                    if was_late and delay is not None:
                        max_delay = delay if max_delay is None else max(max_delay, delay)
                else:
                    dup += 1
                occurred = _record_time(rec, ingested_at)
                if occurred is not None and (newest is None or occurred > newest):
                    newest = occurred
            pages += 1
            window.pages_fetched += 1
            window.records_fetched += len(page.records or [])
            window.recovered_count += late
            window.duplicate_count += dup
            window.rejected_count += rejected
            if max_delay is not None and (window.max_delay_seconds is None or max_delay > window.max_delay_seconds):
                window.max_delay_seconds = max_delay
            if cap.ordering == ORDER_ASCENDING and newest is not None:
                window.checkpoint_at = newest
            step, value = page_end(cap, page, window.records_fetched, limit)
            if step == 'more':
                window.checkpoint_cursor = str(value)[:500]
                window.backfill_attempts = 0
                window.backfill_error = ''
                window.save()
                continue
            window.checkpoint_cursor = ''
            window.checkpoint_at = end if value else window.checkpoint_at
            state, bstate = resolve(cap, proven_end=value, truncated=window.lookback_truncated,
                                    rejected=window.rejected_count, recovered=window.recovered_count,
                                    covered_any=True)
            _finish(window, state, bstate, now)
            _note_found_alerts(window, row)
            return pages, 1
    window.backfill_next_at = now      # more pages: continue on the next tick
    window.save()
    return pages, 0


def _note_found_alerts(window, row):
    """Alerts the backfill stored are open alerts of the source: a healthy
    security source no longer reports "no alerts" because they arrived late."""
    if not window.recovered_count or row is None or row.kind != 'security':
        return
    from integrations.models import IntegrationSyncHealth
    IntegrationSyncHealth.objects.filter(pk=row.pk, health=sh.HEALTHY, alert_status=sh.NO_ALERTS).update(
        alert_status=sh.ACTIVE_ALERTS)


def _ingest_one(adapter, rec, window, now):
    """One record in its own savepoint: a record that cannot be stored is
    counted as rejected and never breaks the page's checkpoint."""
    try:
        with transaction.atomic():
            return adapter.ingest(rec, window, now)
    except Exception:
        logger.warning('backfill: could not store a %s record', adapter.kind, exc_info=True)
        return False, True, False, None


def _record_time(rec, now):
    if isinstance(rec, dict):
        return valid_event_time(rec.get('occurred_at'), now)
    t = getattr(rec, 'finished_at', None) or getattr(rec, 'started_at', None)
    return valid_event_time(t, now) if t else None


def _audit_resolution(window):
    try:
        from audit.models import AuditLog
        from core.models import Organization
        d = coverage_display(window.state, recovered=window.recovered_count)
        AuditLog.log(user=None, action='update',
                     organization=Organization.objects.filter(pk=window.organization_id).first()
                     if window.organization_id else None,
                     object_type='monitoring_coverage_window', object_id=window.pk,
                     object_repr=(window.source_name or window.source_key)[:200],
                     description=(f'Monitoring coverage gap for "{window.source_name or window.source_key}" '
                                  f'resolved: {d.label} ({window.recovered_count} delivered late)'),
                     extra_data={'event': 'monitoring_coverage_resolved', 'state': window.state,
                                 'backfill_state': window.backfill_state, 'recovered': window.recovered_count,
                                 'duplicates': window.duplicate_count, 'failed_reads': window.failed_reads,
                                 'lookback_truncated': window.lookback_truncated})
    except Exception:
        logger.warning('coverage: could not audit a resolution', exc_info=True)


# --- notifications (once per gap) -------------------------------------------------------------

def notify_tick(now=None) -> int:
    from .models import CoverageWindow, EventSettings
    now = now or timezone.now()
    settings = EventSettings.get()
    sent = 0
    if settings.coverage_gap_notify_minutes:
        cutoff = now - timedelta(minutes=settings.coverage_gap_notify_minutes)
        for w in (CoverageWindow.objects.filter(state=COVERAGE_GAP, recovered_at__isnull=True,
                                                notified_prolonged_at__isnull=True, first_failure_at__lte=cutoff)
                  .select_related('health')[:50]):
            if w.health is not None and not w.health.critical:
                continue
            if CoverageWindow.objects.filter(pk=w.pk, notified_prolonged_at__isnull=True).update(
                    notified_prolonged_at=now):
                minutes = int((now - w.first_failure_at).total_seconds() // 60)
                sent += _notify(w, 'prolonged',
                                f'Monitoring coverage gap: "{w.source_name or w.kind}" interrupted for {minutes} min',
                                ['Alerts from this source have not been collected since '
                                 f'{w.coverage_lost_at:%Y-%m-%d %H:%M} UTC ({w.failed_reads} failed reads).',
                                 'Until it recovers, a quiet dashboard for this source does not mean nothing '
                                 'happened.'])
    if settings.coverage_recovery_notify:
        for w in (CoverageWindow.objects.filter(state__in=(PARTIAL_RECOVERY, UNRECOVERABLE_GAP),
                                                notified_unrecovered_at__isnull=True,
                                                resolved_at__gte=now - timedelta(days=2))
                  .select_related('health')[:50]):
            if w.health is not None and not w.health.critical:
                continue
            if CoverageWindow.objects.filter(pk=w.pk, notified_unrecovered_at__isnull=True).update(
                    notified_unrecovered_at=now):
                d = coverage_display(w.state)
                sent += _notify(w, 'unrecovered',
                                f'Monitoring coverage gap not fully recovered: "{w.source_name or w.kind}" ({d.label})',
                                [f'Window {w.coverage_lost_at:%Y-%m-%d %H:%M} – '
                                 f'{(w.recovered_at or now):%Y-%m-%d %H:%M} UTC.',
                                 f'{w.recovered_count} event(s) were delivered late; alerts from this window may '
                                 f'still be missing. {d.tooltip}'])
    return sent


def _notify(window, what, title, lines) -> int:
    from core.models import SystemWarningNotification
    from .source_health_store import _send
    wid = f'coverage:{window.pk}:{what}'
    try:
        _, created = SystemWarningNotification.objects.get_or_create(
            warning_id=wid, defaults={'severity': 'high', 'title': title[:200]})
    except Exception:
        logger.warning('coverage: could not record a notification marker', exc_info=True)
        return 0
    if not created:
        return 0
    body = '\n'.join([title + '.', ''] + lines + ['', 'You get one of these per gap.'])
    transaction.on_commit(lambda: threading.Thread(target=_send, args=(title, body, wid), daemon=True).start())
    return 1


# --- reading ----------------------------------------------------------------------------------

HISTORY_DAYS = 30


def windows_for(source_keys, *, since=None, limit=500):
    from .models import CoverageWindow
    qs = CoverageWindow.objects.filter(source_key__in=list(source_keys))
    if since is not None:
        qs = qs.filter(Q(state=COVERAGE_GAP) | Q(first_failure_at__gte=since))
    return list(qs.order_by('-first_failure_at')[:limit])


def attach(records, now=None):
    """Add coverage to effective health records (in place): the current
    coverage state, the open window and the latest window of the last 30
    days. A source with an unresolved gap is never "no alerts"."""
    now = now or timezone.now()
    keys = [r['source_id'] for r in records if r.get('source_id')]
    by_key = {}
    for w in windows_for(keys, since=now - timedelta(days=HISTORY_DAYS)):
        by_key.setdefault(w.source_key, []).append(w)
    for r in records:
        ws = by_key.get(r.get('source_id'), [])
        open_w = next((w for w in ws if w.state == COVERAGE_GAP), None)
        latest = ws[0] if ws else None
        r['gap_open'] = open_w is not None
        if open_w is not None and r.get('alert_status') == sh.NO_ALERTS:
            r['alert_status'] = sh.UNKNOWN
        r['coverage_state'] = current_state(r, open_w)
        r['coverage_window'] = latest
        r['coverage_windows_30d'] = len(ws)
    return records


def current_state(f, open_window) -> str:
    if open_window is not None:
        return COVERAGE_GAP
    if f.get('kind') == 'push' or f.get('verification') == sh.V_PUSH:
        return NOT_VERIFIED
    if f.get('health') == sh.HEALTHY and f.get('freshness', sh.FRESH) == sh.FRESH:
        if f.get('alert_status') == sh.ACTIVE_ALERTS:
            return ACTIVE_MONITORING
        if f.get('alert_status') == sh.NO_ALERTS:
            return VERIFIED_QUIET
    if f.get('health') in (sh.FAILED, sh.DEGRADED) or f.get('freshness') == sh.STALE and f.get('last_success_at'):
        return COVERAGE_GAP
    return NOT_VERIFIED


def window_contract(w) -> Optional[dict]:
    if w is None:
        return None
    iso = sh._iso
    return {
        'state': w.state, 'cause': w.cause or None,
        'coverage_lost_at': iso(w.coverage_lost_at), 'outage_started_at': iso(w.first_failure_at),
        'recovered_at': iso(w.recovered_at), 'resolved_at': iso(w.resolved_at), 'failed_reads': w.failed_reads,
        'backfill_state': w.backfill_state or None, 'events_delivered_late': w.recovered_count,
        'duplicates_skipped': w.duplicate_count, 'records_rejected': w.rejected_count,
        'max_delivery_delay_seconds': w.max_delay_seconds, 'lookback_truncated': w.lookback_truncated,
        'complete': w.state == RECOVERED_LATE,
    }


def contract_block(f) -> dict:
    """The schema 1.1.0 ``coverage`` object for one record."""
    w = f.get('coverage_window')
    cap = (w.capability if w is not None and w.capability else None)
    return {
        'state': f.get('coverage_state') or NOT_VERIFIED,
        'last_verified_coverage_at': sh._iso(f.get('window_end_complete')),
        'gap': window_contract(w),
        'history_capability': cap or None,
    }
