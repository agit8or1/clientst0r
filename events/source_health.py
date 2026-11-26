"""Monitoring health contract, version 1.1.0 (roadmap 82.7–82.12, 82.15–82.20).

The reference implementation of docs/standards/MONITORING_HEALTH_STANDARD.md.
Pure Python: no models, no I/O, no randomness except the retry jitter. Every
collector, page, notification and AI prompt that talks about whether a
monitoring source is working goes through this module, so "zero alerts" can
never be read as "healthy" by accident.

Four fields are kept independently (standard §2):

  health          healthy | degraded | failed | unknown
  outcome         success | partial | failed | not_attempted
  alert_status    no_alerts | active_alerts | unknown
  reason          authentication_failure | permission_denied |
                  endpoint_unavailable | timeout | rate_limited |
                  invalid_response | ingestion_failed | stale_data |
                  configuration_error | other | '' (none)

The labels people see (Healthy / quiet, Healthy / active, Healthy /
recovering, Degraded, Permission denied, Source unavailable, Ingestion
failed, Stale, Unknown) are derived from those fields by ``display()``;
nothing stores a label. Coverage over time (gaps, backfill, delivered-late
events; schema 1.1.0) lives in events.coverage.

Rules that make this safe:

* ``evaluate()`` is the only function that turns a collection result into
  health. It is deterministic and never consults an AI model.
* An empty result is ``no_alerts`` / ``healthy`` only when the collection was
  verified (a bounded probe passed, or an authenticated connection test ran
  in the same attempt). Otherwise it is ``unknown`` / ``unverified``.
* A failed request, a refused permission or a malformed response is never an
  empty result: the collector passes the exception and gets a failure.
* The newest event time comes from validated timestamps, never from "the
  first record returned" unless the source documents its ordering.
"""
from __future__ import annotations

import secrets as _secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
from typing import Iterable, Optional

SCHEMA_VERSION = '1.1.0'
PRODUCT_ID = 'clientst0r'

# --- the four fields --------------------------------------------------------------------------

HEALTHY, DEGRADED, FAILED, UNKNOWN = 'healthy', 'degraded', 'failed', 'unknown'
HEALTH_VALUES = (HEALTHY, DEGRADED, FAILED, UNKNOWN)

SUCCESS, PARTIAL, NOT_ATTEMPTED = 'success', 'partial', 'not_attempted'
OUTCOME_VALUES = (SUCCESS, PARTIAL, FAILED, NOT_ATTEMPTED)

NO_ALERTS, ACTIVE_ALERTS = 'no_alerts', 'active_alerts'
ALERT_VALUES = (NO_ALERTS, ACTIVE_ALERTS, UNKNOWN)

AUTHENTICATION_FAILURE = 'authentication_failure'
PERMISSION_DENIED = 'permission_denied'
ENDPOINT_UNAVAILABLE = 'endpoint_unavailable'
TIMEOUT = 'timeout'
RATE_LIMITED = 'rate_limited'
INVALID_RESPONSE = 'invalid_response'
INGESTION_FAILED = 'ingestion_failed'
STALE_DATA = 'stale_data'
CONFIGURATION_ERROR = 'configuration_error'
OTHER = 'other'
REASON_VALUES = (AUTHENTICATION_FAILURE, PERMISSION_DENIED, ENDPOINT_UNAVAILABLE, TIMEOUT, RATE_LIMITED,
                 INVALID_RESPONSE, INGESTION_FAILED, STALE_DATA, CONFIGURATION_ERROR, OTHER)

# Reasons that a retry may fix by itself; the rest need a person.
TRANSIENT_REASONS = frozenset({ENDPOINT_UNAVAILABLE, TIMEOUT, RATE_LIMITED})

COMPLETE, UNVERIFIED = 'complete', 'unverified'
COMPLETENESS_VALUES = (COMPLETE, PARTIAL, UNVERIFIED)

# How an empty window was (or was not) verified.
V_PROBE = 'probe_passed'            # bounded verification probe succeeded
V_CONNECTION_TEST = 'connection_test'  # authenticated read in the same attempt
V_RECORDS = 'records_returned'      # the window itself returned records
V_NOT_SUPPORTED = 'not_supported'   # the source offers no way to verify
V_PUSH = 'push_only'                # push source: quiet cannot be confirmed
VERIFICATION_VALUES = ('', V_PROBE, V_CONNECTION_TEST, V_RECORDS, V_NOT_SUPPORTED, V_PUSH)
VERIFIED_EMPTY = frozenset({V_PROBE, V_CONNECTION_TEST})

NEWEST_SOURCE_ORDER = 'source_order'
NEWEST_VALIDATED = 'validated_timestamps'
NEWEST_UNKNOWN = 'unknown'

FRESH, STALE = 'fresh', 'stale'

# A transient failure is Degraded until it repeats this many times.
PERSISTENT_AFTER = 3
# Default freshness threshold when a source sets none: three poll intervals,
# never less than 15 minutes.
DEFAULT_STALE_MINUTES = 120
MIN_STALE_MINUTES = 15
# Timestamps further in the future than this are not trusted (clock skew).
MAX_FUTURE_SKEW = timedelta(minutes=5)
EARLIEST_PLAUSIBLE = datetime(2000, 1, 1, tzinfo=_tz.utc)
MAX_DIAGNOSTIC = 500


# --- collection result ----------------------------------------------------------------------

@dataclass
class CollectionResult:
    """What one collection attempt found. Collectors fill this in; they never
    decide health themselves."""
    attempted_at: datetime
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    retrieved: int = 0          # records the source returned for the window
    processed: int = 0          # records normalized into our shape
    committed: int = 0          # records stored successfully
    rejected: int = 0           # records that could not be normalized or stored
    error: Optional[BaseException] = None   # the collection itself failed
    reason: str = ''            # explicit failure reason (overrides classification)
    verification: str = ''      # one of VERIFICATION_VALUES
    event_times: list = field(default_factory=list)   # raw timestamps of retrieved events
    ordering_guaranteed: bool = False   # the source documents newest-first ordering
    open_alerts: Optional[int] = None   # open alerts from this source after the run, if known
    duration_ms: int = 0
    collection_id: str = ''     # idempotency key for this attempt
    retry_after: Optional[int] = None   # seconds, from the provider
    diagnostic: str = ''        # redacted, short


# --- error classification -------------------------------------------------------------------

def classify_status(status_code: Optional[int]) -> str:
    if status_code is None:
        return ''
    if status_code == 401:
        return AUTHENTICATION_FAILURE
    if status_code == 403:
        return PERMISSION_DENIED
    if status_code in (408, 504):
        return TIMEOUT
    if status_code == 429:
        return RATE_LIMITED
    if status_code in (404, 405, 410):
        return CONFIGURATION_ERROR
    if 500 <= status_code < 600:
        return ENDPOINT_UNAVAILABLE
    if 400 <= status_code < 500:
        return INVALID_RESPONSE
    return ''


_TEXT_RULES = (
    (AUTHENTICATION_FAILURE, ('401', 'unauthorized', 'unauthorised', 'invalid api key', 'invalid credentials',
                              'authentication failed', 'invalid_client', 'invalid_grant', 'token expired',
                              'expired token', 'bad credentials', 'refused the api token')),
    (PERMISSION_DENIED, ('403', 'forbidden', 'access denied', 'permission', 'not authorized',
                         'insufficient privileges', 'insufficient scope')),
    (RATE_LIMITED, ('429', 'rate limit', 'too many requests', 'throttl')),
    (TIMEOUT, ('timed out', 'timeout', 'readtimeout', 'connecttimeout')),
    (ENDPOINT_UNAVAILABLE, ('connection refused', 'name or service not known', 'failed to resolve',
                            'no route to host', 'network is unreachable', 'connectionerror',
                            'max retries exceeded', 'cannot reach', 'connection reset', 'connection aborted',
                            '502', '503', 'service unavailable', 'bad gateway')),
    (INVALID_RESPONSE, ('not json', 'jsondecodeerror', 'malformed', 'unexpected response',
                        'invalid response', 'expecting value')),
    (CONFIGURATION_ERROR, ('no api token configured', 'no base url', 'not configured', '404', 'not found',
                           'address not allowed', 'not implemented')),
)


def classify_text(text: str) -> str:
    t = (text or '').lower()
    for reason, needles in _TEXT_RULES:
        if any(n in t for n in needles):
            return reason
    return OTHER if t else ''


def classify_exception(exc: Optional[BaseException]) -> tuple:
    """(reason, retry_after_seconds or None). Never returns '' for an exception."""
    if exc is None:
        return '', None
    explicit = getattr(exc, 'health_reason', '') or ''
    if explicit in REASON_VALUES:
        return explicit, _retry_after_of(exc)
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None) if response is not None else None
    if status is None:
        status = getattr(exc, 'status_code', None)
    reason = classify_status(status) if isinstance(status, int) else ''
    if not reason:
        name = type(exc).__name__.lower()
        if 'timeout' in name:
            reason = TIMEOUT
        elif 'connection' in name or isinstance(exc, (ConnectionError, OSError)):
            reason = ENDPOINT_UNAVAILABLE
        elif isinstance(exc, ValueError) and ('json' in name or 'decode' in name):
            reason = INVALID_RESPONSE
    if not reason:
        reason = classify_text(f'{type(exc).__name__} {exc}') or OTHER
    return reason, _retry_after_of(exc)


def _retry_after_of(exc) -> Optional[int]:
    value = getattr(exc, 'retry_after', None)
    if value is None:
        response = getattr(exc, 'response', None)
        headers = getattr(response, 'headers', None) or {}
        try:
            value = headers.get('Retry-After')
        except Exception:
            value = None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(seconds, 24 * 3600))


# --- retry policy ---------------------------------------------------------------------------

RETRY_BASE_SECONDS = 60
RETRY_CAP_SECONDS = 3600
_rng = _secrets.SystemRandom()


def next_retry_delay(consecutive_failures: int, retry_after: Optional[int] = None,
                     base: int = RETRY_BASE_SECONDS, cap: int = RETRY_CAP_SECONDS, rng=None) -> int:
    """Exponential backoff with jitter (half fixed, half random), never
    shorter than the provider's Retry-After. 0 when there is no failure."""
    if consecutive_failures <= 0 and not retry_after:
        return 0
    step = min(cap, base * (2 ** max(0, min(consecutive_failures - 1, 16))))
    r = rng or _rng
    delay = int(step / 2 + r.uniform(0, step / 2))
    return max(delay, int(retry_after or 0))


# --- newest event ---------------------------------------------------------------------------

def _parse_time(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return None     # a naive timestamp has no trustworthy zone
    return dt.astimezone(_tz.utc)


def newest_event_time(times: Iterable, now: datetime, ordering_guaranteed: bool = False) -> tuple:
    """(newest datetime or None, basis).

    Without a documented ordering the newest event is the maximum of the
    timestamps that validate (timezone-aware, not before 2000, not in the
    future beyond clock skew). The first record returned is used only when
    the source guarantees newest-first ordering and that record validates.
    No valid timestamp: (None, 'unknown').
    """
    now = now.astimezone(_tz.utc)
    times = list(times or [])
    valid = []
    for raw in times:
        dt = _parse_time(raw)
        if dt is not None and EARLIEST_PLAUSIBLE <= dt <= now + MAX_FUTURE_SKEW:
            valid.append(dt)
    if ordering_guaranteed and times:
        first = _parse_time(times[0])
        if first is not None and first in valid:
            return first, NEWEST_SOURCE_ORDER
    if not valid:
        return None, NEWEST_UNKNOWN
    return max(valid), NEWEST_VALIDATED


# --- evaluation -----------------------------------------------------------------------------

@dataclass
class Previous:
    """The parts of the stored record evaluation needs."""
    last_success_at: Optional[datetime] = None
    consecutive_failures: int = 0
    newest_event_at: Optional[datetime] = None
    newest_event_basis: str = ''
    window_end_complete: Optional[datetime] = None


def evaluate(result: CollectionResult, previous: Optional[Previous] = None) -> dict:
    """The new record fields for one attempt. Deterministic."""
    prev = previous or Previous()
    out = {
        'attempted_at': result.attempted_at,
        'window_start': result.window_start,
        'window_end': result.window_end,
        'retrieved': max(0, int(result.retrieved or 0)),
        'processed': max(0, int(result.processed or 0)),
        'committed': max(0, int(result.committed or 0)),
        'rejected': max(0, int(result.rejected or 0)),
        'duration_ms': max(0, int(result.duration_ms or 0)),
        'verification': result.verification if result.verification in VERIFICATION_VALUES else '',
        'diagnostic': (result.diagnostic or '')[:MAX_DIAGNOSTIC],
        'retry_after': result.retry_after,
        'last_success_at': prev.last_success_at,
        'window_end_complete': prev.window_end_complete,
        'newest_event_at': prev.newest_event_at,
        'newest_event_basis': prev.newest_event_basis or NEWEST_UNKNOWN,
    }
    reason = result.reason if result.reason in REASON_VALUES else ''
    if result.error is not None or (reason and reason != INGESTION_FAILED):
        # The collection itself failed: never an empty result.
        if not reason:
            reason, retry_after = classify_exception(result.error)
            out['retry_after'] = result.retry_after or retry_after
        failures = prev.consecutive_failures + 1
        transient = reason in TRANSIENT_REASONS
        out.update(outcome=FAILED, reason=reason, completeness=UNVERIFIED, consecutive_failures=failures,
                   health=DEGRADED if transient and failures < PERSISTENT_AFTER and prev.last_success_at
                   else FAILED,
                   alert_status=UNKNOWN)
        return out

    newest, basis = newest_event_time(result.event_times, result.attempted_at, result.ordering_guaranteed)
    if newest is not None and (prev.newest_event_at is None or newest > prev.newest_event_at):
        out['newest_event_at'], out['newest_event_basis'] = newest, basis
    elif newest is None and out['retrieved'] and prev.newest_event_at is None:
        out['newest_event_basis'] = NEWEST_UNKNOWN

    retrieved, committed, rejected = out['retrieved'], out['committed'], out['rejected']
    found_alerts = (result.open_alerts if result.open_alerts is not None else committed) > 0

    if retrieved and rejected and not committed:
        # Retrieved but nothing could be stored.
        failures = prev.consecutive_failures + 1
        out.update(outcome=FAILED, reason=INGESTION_FAILED, completeness=PARTIAL, health=FAILED,
                   consecutive_failures=failures,
                   alert_status=ACTIVE_ALERTS if (result.open_alerts or 0) > 0 else UNKNOWN)
        return out
    if rejected:
        out.update(outcome=PARTIAL, reason=INGESTION_FAILED, completeness=PARTIAL, health=DEGRADED,
                   consecutive_failures=0, last_success_at=result.attempted_at,
                   alert_status=ACTIVE_ALERTS if found_alerts else UNKNOWN)
        return out
    if retrieved:
        out.update(outcome=SUCCESS, reason='', completeness=COMPLETE, health=HEALTHY, consecutive_failures=0,
                   last_success_at=result.attempted_at, window_end_complete=result.window_end,
                   verification=out['verification'] or V_RECORDS,
                   alert_status=ACTIVE_ALERTS if found_alerts else NO_ALERTS)
        return out
    # Empty window.
    if out['verification'] in VERIFIED_EMPTY:
        out.update(outcome=SUCCESS, reason='', completeness=COMPLETE, health=HEALTHY, consecutive_failures=0,
                   last_success_at=result.attempted_at, window_end_complete=result.window_end,
                   alert_status=ACTIVE_ALERTS if (result.open_alerts or 0) > 0 else NO_ALERTS)
        return out
    # The query answered, but nothing shows the answer is trustworthy.
    out.update(outcome=SUCCESS, reason='', completeness=UNVERIFIED, health=UNKNOWN, consecutive_failures=0,
               verification=out['verification'] or V_NOT_SUPPORTED,
               alert_status=ACTIVE_ALERTS if (result.open_alerts or 0) > 0 else UNKNOWN)
    return out


def stale_minutes(value) -> int:
    try:
        v = int(value or 0)
    except (TypeError, ValueError):
        v = 0
    return max(MIN_STALE_MINUTES, v) if v else DEFAULT_STALE_MINUTES


def freshness(last_success_at, stale_after_minutes, now) -> str:
    if last_success_at is None:
        return STALE
    return STALE if now - last_success_at > timedelta(minutes=stale_minutes(stale_after_minutes)) else FRESH


def effective(fields: dict, now: datetime) -> dict:
    """Apply the freshness threshold at read time. A source whose last
    successful collection is older than its threshold is never shown as
    healthy or quiet: health becomes unknown (or stays degraded / failed),
    reason ``stale_data`` unless a failure reason is already known, and
    "no alerts" becomes unknown."""
    f = dict(fields)
    if f.get('outcome') in (None, '', NOT_ATTEMPTED) and not f.get('last_success_at'):
        f.update(outcome=NOT_ATTEMPTED, health=UNKNOWN, alert_status=UNKNOWN,
                 completeness=UNVERIFIED, freshness=STALE)
        return f
    fresh = freshness(f.get('last_success_at'), f.get('stale_after_minutes'), now)
    f['freshness'] = fresh
    if fresh == STALE and not f.get('last_success_at'):
        # Never succeeded: there is nothing to be stale; it is unknown (or
        # whatever failure it already has), not "stale data".
        if f.get('health') == HEALTHY:
            f['health'] = UNKNOWN
        if f.get('alert_status') == NO_ALERTS:
            f['alert_status'] = UNKNOWN
        return f
    if f.get('gap_open') and f.get('alert_status') == NO_ALERTS:
        # A coverage gap that is not recovered yet: the quiet is not verified.
        f['alert_status'] = UNKNOWN
    if fresh == STALE:
        if f.get('health') == HEALTHY:
            f['health'] = UNKNOWN
        if not f.get('reason'):
            f['reason'] = STALE_DATA
        if f.get('alert_status') == NO_ALERTS:
            f['alert_status'] = UNKNOWN
        if f.get('completeness') == COMPLETE:
            f['completeness'] = UNVERIFIED
    return f


# --- presentation ---------------------------------------------------------------------------

D_HEALTHY_QUIET = 'healthy_quiet'
D_HEALTHY_ACTIVE = 'healthy_active'
D_RECOVERING = 'healthy_recovering'
D_DEGRADED = 'degraded'
D_PERMISSION = 'permission_denied'
D_UNAVAILABLE = 'source_unavailable'
D_INGESTION = 'ingestion_failed'
D_STALE = 'stale'
D_UNKNOWN = 'unknown'
D_FAILED = 'collection_failed'

DISPLAY = {
    # key: (label, Bootstrap colour, icon, rank — higher is worse)
    D_HEALTHY_QUIET: ('Healthy / quiet', 'success', 'fa-circle-check', 0),
    D_HEALTHY_ACTIVE: ('Healthy / alerts', 'success', 'fa-bell', 1),
    D_RECOVERING: ('Healthy / recovering', 'info', 'fa-clock-rotate-left', 2),
    D_UNKNOWN: ('Unknown', 'secondary', 'fa-circle-question', 2),
    D_DEGRADED: ('Degraded', 'warning', 'fa-triangle-exclamation', 3),
    D_STALE: ('Stale', 'warning', 'fa-hourglass-end', 4),
    D_INGESTION: ('Ingestion failed', 'danger', 'fa-inbox', 5),
    D_FAILED: ('Collection failed', 'danger', 'fa-circle-xmark', 5),
    D_UNAVAILABLE: ('Source unavailable', 'danger', 'fa-plug-circle-xmark', 6),
    D_PERMISSION: ('Permission denied', 'danger', 'fa-lock', 6),
}
REASON_LABELS = {
    AUTHENTICATION_FAILURE: 'Authentication failed', PERMISSION_DENIED: 'Permission denied',
    ENDPOINT_UNAVAILABLE: 'Endpoint unavailable', TIMEOUT: 'Timed out', RATE_LIMITED: 'Rate limited',
    INVALID_RESPONSE: 'Invalid response', INGESTION_FAILED: 'Ingestion failed', STALE_DATA: 'Stale data',
    CONFIGURATION_ERROR: 'Configuration error', OTHER: 'Other error',
}


@dataclass(frozen=True)
class Display:
    key: str
    label: str
    badge: str
    icon: str
    rank: int
    tooltip: str


def display_key(f: dict) -> str:
    health, reason = f.get('health'), f.get('reason') or ''
    if health == HEALTHY:
        if f.get('alert_status') == ACTIVE_ALERTS:
            return D_HEALTHY_ACTIVE
        if f.get('gap_open') or f.get('alert_status') == UNKNOWN:
            return D_RECOVERING
        return D_HEALTHY_QUIET
    if reason in (PERMISSION_DENIED, AUTHENTICATION_FAILURE):
        return D_PERMISSION
    if reason in (ENDPOINT_UNAVAILABLE, TIMEOUT) and health == FAILED:
        return D_UNAVAILABLE
    if reason == INGESTION_FAILED and health == FAILED:
        return D_INGESTION
    if reason == STALE_DATA or (f.get('freshness') == STALE and health != FAILED and f.get('last_success_at')):
        return D_STALE
    if health == DEGRADED:
        return D_DEGRADED
    if health == FAILED:
        return D_FAILED
    return D_UNKNOWN


def display(f: dict) -> Display:
    key = display_key(f)
    label, badge, icon, rank = DISPLAY[key]
    if key == D_PERMISSION and f.get('reason') == AUTHENTICATION_FAILURE:
        label = 'Authentication failed'
    return Display(key, label, badge, icon, rank, tooltip(f, key))


def tooltip(f: dict, key: str = '') -> str:
    key = key or display_key(f)
    parts = {
        D_HEALTHY_QUIET: 'Collection verified; no qualifying alerts in the window.',
        D_HEALTHY_ACTIVE: 'Collection verified; alerts were found.',
        D_RECOVERING: ('Collection works again, but the window it missed is not recovered yet, so the quiet '
                       'period is not verified.'),
        D_UNKNOWN: ('Collection has not been verified, so an empty result cannot be trusted.'
                    if f.get('outcome') != NOT_ATTEMPTED else 'No collection has run yet.'),
        D_DEGRADED: 'Collection is partly working; some data may be missing.',
        D_STALE: 'The last successful collection is older than this source\'s freshness threshold.',
        D_INGESTION: 'Data was retrieved but could not be stored.',
        D_FAILED: 'The last collections failed.',
        D_UNAVAILABLE: 'The source could not be reached.',
        D_PERMISSION: 'The source refused the credentials or their permissions.',
    }[key]
    if f.get('reason') and f.get('reason') != STALE_DATA:
        parts += f' Reason: {REASON_LABELS.get(f["reason"], f["reason"])}.'
    if f.get('verification') == V_PUSH:
        parts += ' Push-only source: a quiet period cannot be confirmed.'
    return parts


def is_verified_healthy(f: dict) -> bool:
    return f.get('health') == HEALTHY and f.get('freshness', FRESH) == FRESH and not f.get('gap_open')


# Coverage window states that leave alerts possibly missing (events.coverage).
UNRESOLVED_WINDOWS = ('partial_recovery', 'unrecoverable_gap')
RECENT_GAP_HOURS = 24


# --- aggregation and AI context -------------------------------------------------------------

def summarize(records: Iterable[dict]) -> dict:
    """Roll records (already passed through ``effective``) up for a customer
    or the whole MSP. ``verified`` is True only when every critical source is
    verified healthy; one failed, stale or unknown critical source makes the
    whole scope unverified."""
    records = list(records)
    counts = {k: 0 for k in DISPLAY}
    worst, gaps = None, []
    for r in records:
        d = display(r)
        counts[d.key] += 1
        if worst is None or d.rank > worst.rank:
            worst = d
        if not is_verified_healthy(r):
            gaps.append({'name': r.get('name', ''), 'kind': r.get('kind', ''), 'state': d.key,
                         'label': d.label, 'critical': bool(r.get('critical', True)),
                         'last_success_at': r.get('last_success_at'), 'reason': r.get('reason', '')})
    critical_gaps = [g for g in gaps if g['critical']]
    alerts = any(r.get('alert_status') == ACTIVE_ALERTS for r in records)
    # Recent gaps that were not fully recovered: current collection may be
    # fine, but alerts from that window may be missing.
    missing = []
    for r in records:
        w = r.get('coverage_window')
        if w is not None and getattr(w, 'state', '') in UNRESOLVED_WINDOWS and w.resolved_at and \
                (w.recovered_at or w.resolved_at) >= _reference_time(records) - timedelta(hours=RECENT_GAP_HOURS):
            missing.append({'name': r.get('name', ''), 'state': w.state, 'from': w.coverage_lost_at,
                            'to': w.recovered_at or w.resolved_at})
    return {
        'total': len(records), 'counts': counts, 'gaps': gaps, 'critical_gaps': critical_gaps,
        'missing_windows': missing,
        'verified': bool(records) and not critical_gaps,
        'worst': worst, 'has_alerts': alerts,
        'alert_status': (ACTIVE_ALERTS if alerts else NO_ALERTS if records and not critical_gaps else UNKNOWN),
    }


def _reference_time(records):
    """'Now' for a roll-up: the newest attempt in it (this module reads no clock)."""
    times = [r.get('attempted_at') for r in records if r.get('attempted_at')]
    return max(times) if times else datetime.now(_tz.utc)


def _missing_sentence(summary):
    m = summary.get('missing_windows') or []
    if not m:
        return ''
    # In the install's time zone, named, so the sentence matches the tables on
    # the page (which Django renders in that zone) and stays unambiguous elsewhere.
    from django.utils import timezone as dj_tz

    def _local(dt):
        return dj_tz.localtime(dt) if dj_tz.is_aware(dt) else dt
    names = ', '.join(f"{g['name']} ({_local(g['from']):%Y-%m-%d %H:%M}–{_local(g['to']):%H:%M %Z})"
                      for g in m[:4])
    return (f' Alerts from {names} may be missing: the coverage gap could not be fully recovered.')


def visibility_statement(summary: dict) -> str:
    """The deterministic sentence any report or AI output about this scope
    must carry. Built here, outside the model."""
    if not summary['total']:
        return ('No monitoring source reports health for this scope, so its security status cannot be '
                'verified.')
    if summary['verified']:
        return ('Every monitoring source in scope was verified within its freshness threshold.'
                + _missing_sentence(summary))
    names = ', '.join(f"{g['name'] or g['kind']} ({g['label'].lower()})" for g in summary['critical_gaps'][:6])
    more = len(summary['critical_gaps']) - 6
    if more > 0:
        names += f' and {more} more'
    lead = ('Alerts were found in the successfully monitored sources.' if summary['has_alerts']
            else 'Zero threats detected in the successfully monitored sources.')
    return (f'{lead} Monitoring is not verified for {names}, so overall security status cannot be verified.'
            + _missing_sentence(summary))


def ai_context(summary: dict) -> dict:
    """Source-health facts to pass to an AI analysis. Names, states and
    times only: no credentials, no error text, no event content."""
    return {
        'monitoring_verified': summary['verified'],
        'visibility_statement': visibility_statement(summary),
        'sources_total': summary['total'],
        'gaps': [{'source': g['name'] or g['kind'], 'state': g['state'], 'critical': g['critical'],
                  'last_successful_collection': g['last_success_at'].isoformat() if g['last_success_at'] else None}
                 for g in summary['gaps'][:25]],
    }


HEALTHY_CLAIMS = ('all clear', 'fully healthy', 'environment is healthy', 'environment is secure',
                  'no threats', 'no issues', 'everything is healthy', 'all systems healthy', 'nothing to report')


def guard_ai_text(text: str, summary: dict) -> tuple:
    """(text, changed). When monitoring is not verified, an AI text must
    lead with the visibility statement; a text claiming the environment is
    healthy is not allowed to stand on its own."""
    if summary['verified']:
        return text, False
    statement = visibility_statement(summary)
    if statement in (text or ''):
        return text, False
    return f'{statement}\n\n{text or ""}'.strip(), True


# --- machine-readable contract --------------------------------------------------------------

def _iso(dt):
    return dt.astimezone(_tz.utc).isoformat().replace('+00:00', 'Z') if dt else None


def to_contract(f: dict, *, tenant_id, source_id: str, source_type: str, product_id: str = PRODUCT_ID) -> dict:
    """The schema 1.0.0 payload (docs/standards/monitoring-health/schema-1.0.0.json)."""
    return {
        'schema_version': SCHEMA_VERSION,
        'product_id': product_id,
        'tenant_id': None if tenant_id is None else str(tenant_id),
        'source_id': str(source_id),
        'source_type': source_type,
        'health': f.get('health') or UNKNOWN,
        'collection_outcome': f.get('outcome') or NOT_ATTEMPTED,
        'alert_status': f.get('alert_status') or UNKNOWN,
        'failure_reason': f.get('reason') or None,
        'completeness': f.get('completeness') or UNVERIFIED,
        'verification': f.get('verification') or None,
        'freshness': f.get('freshness') or STALE,
        'freshness_threshold_minutes': stale_minutes(f.get('stale_after_minutes')),
        'last_attempt_at': _iso(f.get('attempted_at')),
        'last_success_at': _iso(f.get('last_success_at')),
        'query_window': ({'start': _iso(f.get('window_start')), 'end': _iso(f.get('window_end'))}
                         if f.get('window_start') or f.get('window_end') else None),
        'records': {'retrieved': f.get('retrieved') or 0, 'processed': f.get('processed') or 0,
                    'rejected': f.get('rejected') or 0, 'committed': f.get('committed') or 0},
        'newest_event_at': _iso(f.get('newest_event_at')),
        'newest_event_basis': f.get('newest_event_basis') or NEWEST_UNKNOWN,
        'consecutive_failures': f.get('consecutive_failures') or 0,
        'duration_ms': f.get('duration_ms') or 0,
        'display_state': display_key(f),
        'diagnostic': (f.get('diagnostic') or '')[:MAX_DIAGNOSTIC] or None,
        # 1.1.0: coverage over time (events.coverage); null when not tracked.
        'coverage': f.get('coverage') if 'coverage' in f else None,
    }


REQUIRED = ('schema_version', 'product_id', 'tenant_id', 'source_id', 'source_type', 'health',
            'collection_outcome', 'alert_status', 'failure_reason', 'completeness', 'freshness',
            'freshness_threshold_minutes', 'last_attempt_at', 'last_success_at', 'records',
            'newest_event_at', 'consecutive_failures')
_ENUMS = {'health': HEALTH_VALUES, 'collection_outcome': OUTCOME_VALUES, 'alert_status': ALERT_VALUES,
          'completeness': COMPLETENESS_VALUES, 'freshness': (FRESH, STALE),
          'newest_event_basis': (NEWEST_SOURCE_ORDER, NEWEST_VALIDATED, NEWEST_UNKNOWN)}


def validate(payload: dict) -> list:
    """Errors in a schema 1.0.0 payload ([] = valid). Implements the JSON
    Schema's rules plus the cross-field rules the schema cannot express."""
    errors = []
    if not isinstance(payload, dict):
        return ['payload is not an object']
    for key in REQUIRED:
        if key not in payload:
            errors.append(f'missing {key}')
    if errors:
        return errors
    if str(payload['schema_version']).split('.')[0] != SCHEMA_VERSION.split('.')[0]:
        errors.append('unsupported schema_version')
    for key, allowed in _ENUMS.items():
        if key in payload and payload[key] not in allowed:
            errors.append(f'{key} not one of {allowed}')
    if payload['failure_reason'] is not None and payload['failure_reason'] not in REASON_VALUES:
        errors.append('failure_reason not a known reason')
    for key in ('last_attempt_at', 'last_success_at', 'newest_event_at'):
        v = payload.get(key)
        if v is not None and (not isinstance(v, str) or not v.endswith('Z') or _parse_time(v) is None):
            errors.append(f'{key} must be an ISO 8601 UTC timestamp ending in Z, or null')
    rec = payload['records']
    if not isinstance(rec, dict) or any(not isinstance(rec.get(k), int) or rec.get(k) < 0
                                        for k in ('retrieved', 'processed', 'rejected', 'committed')):
        errors.append('records needs non-negative integers retrieved, processed, rejected, committed')
    elif rec['retrieved'] and rec['committed'] > rec['retrieved']:
        errors.append('records.committed cannot exceed what was retrieved')
    if not isinstance(payload['consecutive_failures'], int) or payload['consecutive_failures'] < 0:
        errors.append('consecutive_failures must be a non-negative integer')
    t = payload['freshness_threshold_minutes']
    if not isinstance(t, int) or not (MIN_STALE_MINUTES <= t <= 43200):
        errors.append('freshness_threshold_minutes must be 15..43200')
    # Cross-field rules (standard §2.3).
    if payload['health'] == HEALTHY:
        if payload['collection_outcome'] not in (SUCCESS,):
            errors.append('healthy requires collection_outcome success')
        if payload['completeness'] != COMPLETE:
            errors.append('healthy requires completeness complete')
        if payload['freshness'] != FRESH:
            errors.append('healthy requires freshness fresh')
    if payload['alert_status'] == NO_ALERTS and payload['health'] != HEALTHY:
        errors.append('no_alerts requires verified healthy collection')
    if payload['collection_outcome'] == FAILED and not payload['failure_reason']:
        errors.append('a failed collection needs a failure_reason')
    if payload.get('display_state') is not None and payload['display_state'] not in DISPLAY:
        errors.append('display_state not a known state')
    errors += _validate_coverage(payload)
    return errors


COVERAGE_STATES = ('verified_quiet', 'active_monitoring', 'coverage_gap', 'recovered_late', 'partial_recovery',
                   'unrecoverable_gap', 'not_verified')
WINDOW_STATES = ('coverage_gap', 'recovered_late', 'partial_recovery', 'unrecoverable_gap')


def _validate_coverage(payload) -> list:
    """Rules for the optional 1.1.0 ``coverage`` object."""
    cov = payload.get('coverage')
    if cov is None:
        return []
    if not isinstance(cov, dict):
        return ['coverage must be an object or null']
    errors = []
    state = cov.get('state')
    if state not in COVERAGE_STATES:
        errors.append('coverage.state not a known state')
    gap = cov.get('gap')
    if gap is not None and (not isinstance(gap, dict) or gap.get('state') not in WINDOW_STATES):
        errors.append('coverage.gap.state not a known window state')
        gap = None
    for key in ('last_verified_coverage_at',):
        v = cov.get(key)
        if v is not None and (not isinstance(v, str) or not v.endswith('Z') or _parse_time(v) is None):
            errors.append(f'coverage.{key} must be an ISO 8601 UTC timestamp ending in Z, or null')
    if state == 'verified_quiet':
        if payload['health'] != HEALTHY or payload['alert_status'] != NO_ALERTS:
            errors.append('coverage verified_quiet requires healthy collection with no_alerts')
        if gap is not None and gap.get('state') == 'coverage_gap':
            errors.append('coverage verified_quiet cannot have an open gap')
    if gap is not None and gap.get('state') == 'coverage_gap' and payload['alert_status'] == NO_ALERTS:
        errors.append('an open coverage gap cannot report no_alerts')
    if gap is not None and gap.get('state') == 'coverage_gap' and state != 'coverage_gap':
        errors.append('an open coverage gap makes coverage.state coverage_gap')
    if gap is not None and bool(gap.get('complete')) != (gap.get('state') == 'recovered_late'):
        errors.append('coverage.gap.complete is true exactly when the gap is recovered_late')
    if gap is not None and gap.get('state') == 'recovered_late':
        cap = cov.get('history_capability') or {}
        if not (cap.get('supports_history') is True and cap.get('max_lookback_minutes')
                and cap.get('ordering') in ('ascending', 'descending', 'unordered')
                and cap.get('pagination') in ('cursor_exhausted', 'short_page', 'total_count')):
            errors.append('a recovered_late gap needs a fully declared history capability')
        if gap.get('lookback_truncated'):
            errors.append('a recovered_late gap cannot be lookback_truncated')
    return errors
