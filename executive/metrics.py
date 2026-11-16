"""The metric framework: filters, scope, results and the provider base class.

A provider answers one question ("what is MRR?") from one data source. It
returns a `Collected` — the rows that make up the number plus the number
itself — and the framework turns that into the card's `MetricResult` and the
drill-down list. Because both come from the same `collect()` call, the
drill-down is always exactly the records behind the value.

States
  ok              a value was computed (it may still be incomplete: see
                  `is_complete` / `unknown_reason`)
  not_configured  the data source is not installed or not set up here (an
                  app that is not installed, a reporting function this server
                  does not have yet, no integration connected). No value, never
                  a zero.
  forbidden       the viewer's role does not cover this metric (or the chosen
                  customer)
  error           the provider raised; the reason is logged, not shown

Scope (tenant isolation)
  One MSP per install; an Organization is a customer. Every card needs its
  permission across customers (`reports.access.has_msp_wide_perm`, the
  technician's global role) and is computed over the technician's client
  scope (`reports.access.viewer_client_scope`: None = every customer, else a
  list) — the rule the profitability reports use. Customer users hold no
  MSP-wide permission, so they see nothing. A customer filter can only narrow
  the scope; a customer outside it is forbidden, not "zero".
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)

STATE_OK = 'ok'
STATE_NOT_CONFIGURED = 'not_configured'
STATE_FORBIDDEN = 'forbidden'
STATE_ERROR = 'error'

# The filters a provider may declare support for.
F_DATE = 'date_range'
F_CUSTOMER = 'customer'
F_SERVICE_LINE = 'service_line'
F_LOCATION = 'location'
ALL_FILTERS = (F_DATE, F_CUSTOMER, F_SERVICE_LINE, F_LOCATION)
FILTER_LABELS = {
    F_DATE: 'Date range',
    F_CUSTOMER: 'Customer',
    F_SERVICE_LINE: 'Service line',
    F_LOCATION: 'Location',
}

CACHE_SECONDS = 300
CACHE_VERSION = 1
# Rows a drill-down returns at most; a capped list says so.
DRILLDOWN_LIMIT = 2000


class NotConfigured(Exception):
    """Raised by a provider when its data source is missing."""


class Forbidden(Exception):
    """Raised when the viewer may not see the requested slice."""


def _parse_date(raw, default):
    if not raw:
        return default
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return default


def _parse_int(raw):
    raw = (raw or '').strip() if isinstance(raw, str) else raw
    if raw in (None, ''):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def default_range(today=None):
    """The last twelve months: the first day of the month eleven months ago
    to today."""
    today = today or timezone.localdate()
    y, m = today.year, today.month - 11
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1), today


@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    customer: Optional[int] = None
    service_line: str = ''
    location: Optional[int] = None

    @classmethod
    def from_query(cls, params, today=None):
        d_start, d_end = default_range(today)
        start = _parse_date(params.get('start'), d_start)
        end = _parse_date(params.get('end'), d_end)
        if end < start:
            start, end = end, start
        # A window longer than three years is cut back: every provider loops
        # over months at most, but nobody needs a decade of sparkline.
        if (end - start).days > 366 * 3:
            start = end - timedelta(days=366 * 3)
        from psa.models import Contract
        service_line = (params.get('service_line') or '').strip()
        if service_line not in dict(Contract.CONTRACT_TYPES):
            service_line = ''
        return cls(start=start, end=end, customer=_parse_int(params.get('customer')),
                   service_line=service_line, location=_parse_int(params.get('location')))

    def active(self):
        """The filters the viewer actually set (date range always counts)."""
        out = [F_DATE]
        if self.customer:
            out.append(F_CUSTOMER)
        if self.service_line:
            out.append(F_SERVICE_LINE)
        if self.location:
            out.append(F_LOCATION)
        return out

    def as_query(self):
        q = {'start': self.start.isoformat(), 'end': self.end.isoformat()}
        if self.customer:
            q['customer'] = str(self.customer)
        if self.service_line:
            q['service_line'] = self.service_line
        if self.location:
            q['location'] = str(self.location)
        return q

    def for_provider(self, supported):
        """These filters with the unsupported ones cleared, so an ignored
        filter cannot change a value (or split the cache)."""
        return Filters(
            start=self.start, end=self.end,
            customer=self.customer if F_CUSTOMER in supported else None,
            service_line=self.service_line if F_SERVICE_LINE in supported else '',
            location=self.location if F_LOCATION in supported else None,
        )


@dataclass(frozen=True)
class Scope:
    """What one viewer may see for one metric.

    The same rule the reports use (reports.views profitability pages): the
    permission is read MSP-wide (`reports.access.has_msp_wide_perm`, the
    technician's global role), and the customers are the technician's client
    scope (`reports.access.viewer_client_scope`). Customer users never hold an
    MSP-wide permission, so every scope of theirs is empty.
    """
    user: object
    perm: str
    org_ids: Optional[frozenset]   # None = every customer of the install
    allowed: bool = True

    @classmethod
    def for_user(cls, user, perm, legacy='membership'):
        from reports.access import has_msp_wide_perm, viewer_client_scope
        if not has_msp_wide_perm(user, perm, legacy=legacy):
            return cls(user=user, perm=perm, org_ids=frozenset(), allowed=False)
        ids = viewer_client_scope(user)
        return cls(user=user, perm=perm, org_ids=None if ids is None else frozenset(ids))

    @property
    def empty(self):
        return self.org_ids is not None and not self.org_ids

    def other(self, perm):
        """The same viewer's scope for another permission."""
        return Scope.for_user(self.user, perm)

    def customer_ids(self, filters):
        """The customer ids a query should be limited to (None = no limit).

        A customer filter narrows the scope; one outside it is Forbidden."""
        if not self.allowed:
            raise Forbidden(f"Your role does not include the '{self.perm}' permission.")
        if filters.customer:
            if self.org_ids is not None and filters.customer not in self.org_ids:
                raise Forbidden('You do not have access to that customer for this metric.')
            return frozenset({filters.customer})
        if self.empty:
            raise Forbidden('Your role does not include this metric for any customer.')
        return self.org_ids

    def cache_part(self):
        if self.org_ids is None:
            return 'all'
        return ','.join(str(i) for i in sorted(self.org_ids))


def limit_to(qs, field, ids):
    """Narrow `qs` to rows whose `field` is one of `ids` (None = no limit)."""
    if ids is None:
        return qs
    return qs.filter(**{f'{field}__in': list(ids)})


def limit_customer_or_owner(qs, ids, customer='client_org', owner='organization'):
    """For records whose customer is optional (`client_org` null means the
    record is the owning organization's own): the customer, else the owner."""
    if ids is None:
        return qs
    from django.db.models import Q
    ids = list(ids)
    return qs.filter(Q(**{f'{customer}__in': ids})
                     | Q(**{f'{customer}__isnull': True, f'{owner}__in': ids}))


def months_between(start, end):
    """[(label 'YYYY-MM', first day, last day clipped to end), ...]."""
    out = []
    cur = start.replace(day=1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        out.append((cur.strftime('%Y-%m'), max(cur, start), min(end, nxt - timedelta(days=1))))
        cur = nxt
    return out


def _plain(value):
    """JSON-safe copy of `value` (Decimals → float, dates → ISO)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    return value


@dataclass
class Column:
    key: str
    label: str
    kind: str = 'text'   # text | currency | number | hours | percent | date | bool


@dataclass
class Collected:
    """What a provider's collect() returns."""
    value: object
    rows: list = field(default_factory=list)
    trend: list = field(default_factory=list)        # [{'label', 'value'}]
    breakdown: list = field(default_factory=list)    # [{'label', 'value', 'part'?, 'unit'?}]
    is_complete: bool = True
    unknown_reason: str = ''
    notes: list = field(default_factory=list)
    secondary: str = ''          # one short line under the value
    source: str = ''             # overrides the provider's source text
    unit: str = ''               # overrides the provider's unit


@dataclass
class MetricResult:
    key: str
    title: str
    state: str
    value: object = None
    unit: str = ''
    trend: list = field(default_factory=list)
    breakdown: list = field(default_factory=list)
    is_complete: bool = True
    unknown_reason: str = ''
    source: str = ''
    as_of: str = ''
    drilldown_url: str = ''
    label: str = ''
    secondary: str = ''
    notes: list = field(default_factory=list)
    reason: str = ''             # why the state is not ok
    supported_filters: list = field(default_factory=list)
    ignored_filters: list = field(default_factory=list)
    row_count: int = 0
    cached: bool = False

    def to_dict(self):
        return _plain(asdict(self))


class MetricProvider:
    """Base class. Subclasses set the attributes and implement collect()."""
    key = ''
    title = ''
    section = ''
    icon = 'fa-chart-line'
    unit = 'count'           # currency | count | percent | hours
    chart = 'line'           # line | bar | none — how the trend / breakdown is drawn
    label = ''               # a caveat shown on the card ("operational estimate …")
    source = ''
    permission = 'reports_view_financial'
    permission_note = ''
    supported_filters = (F_DATE, F_CUSTOMER)
    columns: tuple = ()
    # Default ordering of the card on the page.
    order = 100
    # A provider whose value is a point in time ("now") rather than a window.
    point_in_time = False

    def permission_key(self):
        return self.permission

    def availability(self):
        """None when the data source is available, else the reason it is not."""
        return None

    def collect(self, scope, filters):  # pragma: no cover - abstract
        raise NotImplementedError

    def as_of(self, filters):
        if self.point_in_time:
            return timezone.now()
        return filters.end

    # -- helpers -----------------------------------------------------------
    def meta(self):
        return {
            'key': self.key, 'title': self.title, 'section': self.section, 'icon': self.icon,
            'unit': self.unit, 'chart': self.chart, 'label': self.label, 'source': self.source,
            'supported_filters': list(self.supported_filters),
            'permission': self.permission_key(), 'permission_note': self.permission_note,
        }


def _cache_key(provider, scope, filters, kind):
    raw = json.dumps([CACHE_VERSION, kind, provider.key, scope.perm, scope.cache_part(),
                      filters.as_query()], sort_keys=True)
    return 'executive:' + hashlib.sha256(raw.encode()).hexdigest()


def _base_result(provider, state, filters, **kw):
    supported = list(provider.supported_filters)
    ignored = [f for f in filters.active() if f not in supported]
    return MetricResult(key=provider.key, title=provider.title, state=state,
                        unit=provider.unit, source=provider.source, label=provider.label,
                        supported_filters=supported, ignored_filters=ignored, **kw)


def _collect(provider, scope, filters, use_cache=True):
    """(Collected | None, state, reason). Cached per (provider, scope, filters)."""
    reason = provider.availability()
    if reason:
        return None, STATE_NOT_CONFIGURED, reason
    if not scope.allowed:
        return None, STATE_FORBIDDEN, f"Your role does not include the '{scope.perm}' permission."
    if scope.empty:
        return None, STATE_FORBIDDEN, 'Your client scope includes no customers.'
    key = _cache_key(provider, scope, filters, 'collect')
    if use_cache:
        hit = cache.get(key)
        if hit is not None:
            return hit, STATE_OK, 'cached'
    try:
        collected = provider.collect(scope, filters)
    except NotConfigured as exc:
        return None, STATE_NOT_CONFIGURED, str(exc)
    except Forbidden as exc:
        return None, STATE_FORBIDDEN, str(exc)
    except Exception:  # noqa: BLE001 - one bad provider must not break the page
        log.exception('executive metric %s failed', provider.key)
        return None, STATE_ERROR, 'This metric could not be computed. The error has been logged.'
    if use_cache:
        cache.set(key, collected, CACHE_SECONDS)
    return collected, STATE_OK, ''


def compute(provider, user, filters, drilldown_url='', use_cache=True):
    """The card for `provider` as `user` sees it under `filters`."""
    scope = Scope.for_user(user, provider.permission_key())
    pfilters = filters.for_provider(provider.supported_filters)
    collected, state, reason = _collect(provider, scope, pfilters, use_cache)
    as_of = provider.as_of(pfilters)
    if state != STATE_OK:
        return _base_result(provider, state, filters, reason=reason,
                            as_of=_plain(as_of) if state == STATE_OK else '')
    res = _base_result(
        provider, STATE_OK, filters,
        value=collected.value, trend=collected.trend, breakdown=collected.breakdown,
        is_complete=collected.is_complete, unknown_reason=collected.unknown_reason,
        as_of=_plain(as_of), drilldown_url=drilldown_url, secondary=collected.secondary,
        notes=list(collected.notes), row_count=len(collected.rows), cached=reason == 'cached',
    )
    if collected.source:
        res.source = collected.source
    if collected.unit:
        res.unit = collected.unit
    return res


def drilldown(provider, user, filters, part='', use_cache=True):
    """(MetricResult, columns, rows, capped) — the records behind the value."""
    scope = Scope.for_user(user, provider.permission_key())
    pfilters = filters.for_provider(provider.supported_filters)
    collected, state, reason = _collect(provider, scope, pfilters, use_cache)
    if state != STATE_OK:
        return _base_result(provider, state, filters, reason=reason), [], [], False
    rows = collected.rows
    if part:
        rows = [r for r in rows if r.get('part') == part]
    capped = len(rows) > DRILLDOWN_LIMIT
    result = compute(provider, user, filters, use_cache=use_cache)
    return result, list(provider.columns), [_plain(r) for r in rows[:DRILLDOWN_LIMIT]], capped
