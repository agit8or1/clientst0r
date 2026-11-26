"""Monitoring source health: recording, freshness sweep, notifications and the
per-customer roll-up (roadmap 82.7–82.11).

Storage reuses ``integrations.IntegrationSyncHealth`` (one row per
connection and kind, generic FK, already redacted and already read by the
integration pages); this module adds the contract fields to it through
``record_collection()``. Decisions come from ``events.source_health``.

Isolation: a collector can write only the row of its own connection
(content type + id + kind), and the row's customer is copied from the
connection, never from the payload. A broken or hostile integration can
therefore not change the health of another source or another customer.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import source_health as sh

logger = logging.getLogger('events.source_health')

# Kinds that are monitoring sources (shown on the reliability page, rolled up
# per customer, notified). Inventory syncs (PSA, network controllers, M365)
# keep their existing health page.
MONITORING_KINDS = ('security', 'rmm', 'backup')
KIND_LABELS = {'security': 'Security connector', 'rmm': 'RMM', 'backup': 'Backup monitoring',
               'monitor': 'Website monitor', 'push': 'Security webhook / SIEM', 'pipeline': 'Event pipeline'}
# Default freshness thresholds (minutes) when a row sets none.
KIND_STALE = {'security': 60, 'rmm': 180, 'backup': 180}
NOTIFY_WINDOW = timedelta(minutes=30)
ALERTING = frozenset({sh.D_PERMISSION, sh.D_UNAVAILABLE, sh.D_INGESTION, sh.D_FAILED, sh.D_STALE})


# --- writing --------------------------------------------------------------------------------

def _row_for(conn, kind):
    from django.contrib.contenttypes.models import ContentType
    from integrations.models import IntegrationSyncHealth
    ct = ContentType.objects.get_for_model(type(conn))
    row, _ = IntegrationSyncHealth.objects.get_or_create(
        content_type=ct, object_id=conn.pk, kind=kind,
        defaults={'organization_id': customer_of(conn)})
    return row


def customer_of(conn):
    """The customer a connection's health belongs to: the pinned client when
    the connection has one, else its organization (None = MSP-wide)."""
    return getattr(conn, 'client_org_id', None) or getattr(conn, 'organization_id', None)


def default_stale_minutes(conn, kind):
    interval = getattr(conn, 'poll_interval_minutes', None) or getattr(conn, 'sync_interval_minutes', None)
    if interval:
        return max(sh.MIN_STALE_MINUTES, int(interval) * 3)
    return KIND_STALE.get(kind, sh.DEFAULT_STALE_MINUTES)


def previous_of(row) -> sh.Previous:
    return sh.Previous(last_success_at=row.last_success_at, consecutive_failures=row.consecutive_failures, newest_event_at=row.newest_event_at,
                       newest_event_basis=row.newest_event_basis, window_end_complete=row.window_end_complete)


def record_collection(conn, kind: str, result: sh.CollectionResult, *, legacy_status=True):
    """Store one collection attempt. Returns the row (or None on a storage
    error: health bookkeeping never breaks a collection)."""
    from integrations.health import credential_values, redact, suggest_action
    try:
        with transaction.atomic():
            row = _row_for(conn, kind)
            row = type(row).objects.select_for_update().get(pk=row.pk)
            if result.collection_id and result.collection_id == row.last_collection_id:
                return row      # the same attempt reported twice: no double counting
            secrets = credential_values(conn)
            result.diagnostic = redact(result.diagnostic or (str(result.error) if result.error else ''),
                                       secrets)[:sh.MAX_DIAGNOSTIC]
            previous_cursor = row.window_end_complete or row.last_success_at
            f = sh.evaluate(result, previous_of(row))
            row.organization_id = customer_of(conn)
            row.health = f['health']
            row.collection_outcome = f['outcome']
            row.alert_status = f['alert_status']
            row.failure_reason = f['reason']
            row.completeness = f['completeness']
            row.verification = f['verification']
            row.window_start, row.window_end = f['window_start'], f['window_end']
            row.window_end_complete = f['window_end_complete']
            row.retrieved_count, row.processed_count = f['retrieved'], f['processed']
            row.committed_count, row.rejected_count = f['committed'], f['rejected']
            row.newest_event_at, row.newest_event_basis = f['newest_event_at'], f['newest_event_basis']
            row.duration_ms = f['duration_ms']
            row.consecutive_failures = f['consecutive_failures']
            row.last_collection_id = (result.collection_id or '')[:80]
            if row.stale_after_minutes is None:
                row.stale_after_minutes = default_stale_minutes(conn, kind)
            delay = sh.next_retry_delay(row.consecutive_failures, f['retry_after']) \
                if f['outcome'] == sh.FAILED else int(f['retry_after'] or 0)
            row.next_attempt_at = result.attempted_at + timedelta(seconds=delay) if delay else None
            # The pre-contract fields keep their meaning for the existing pages.
            row.last_attempt_at = result.attempted_at
            row.last_success_at = f['last_success_at']
            if legacy_status:
                row.status = {sh.SUCCESS: 'success', sh.PARTIAL: 'partial'}.get(f['outcome'], 'error')
                row.created_count = f['committed']
                row.failed_count = f['rejected']
                row.error = f['diagnostic'] if f['outcome'] != sh.SUCCESS else ''
                row.corrective_action = suggest_action(row.error, conn) if row.error else ''
            row.save()
            # Coverage over time (82.15): open, extend or recover the gap.
            from . import coverage
            coverage.on_collection(row, f, result.attempted_at, name=getattr(conn, 'name', ''),
                                   previous_cursor=previous_cursor)
            _transition(row, fields_of(row, name=getattr(conn, 'name', '')), result.attempted_at)
            return row
    except Exception:
        logger.exception('could not record source health for %s', conn)
        return None


def due(conn, kind, now=None) -> bool:
    """False while the retry backoff (or the provider's Retry-After) says
    to wait. Never blocks a source that has no row yet."""
    from django.contrib.contenttypes.models import ContentType
    from integrations.models import IntegrationSyncHealth
    ct = ContentType.objects.get_for_model(type(conn))
    nxt = (IntegrationSyncHealth.objects.filter(content_type=ct, object_id=conn.pk, kind=kind)
           .values_list('next_attempt_at', flat=True).first())
    return nxt is None or nxt <= (now or timezone.now())


def cursor(conn, kind):
    """End of the last completely collected window, or None. A failed or
    partial attempt never moves it, so its window is asked for again."""
    from django.contrib.contenttypes.models import ContentType
    from integrations.models import IntegrationSyncHealth
    ct = ContentType.objects.get_for_model(type(conn))
    return (IntegrationSyncHealth.objects.filter(content_type=ct, object_id=conn.pk, kind=kind)
            .values_list('window_end_complete', flat=True).first())


# --- reading --------------------------------------------------------------------------------

def fields_of(row, name='') -> dict:
    return {
        'name': name, 'kind': row.kind, 'organization_id': row.organization_id, 'critical': row.critical,
        'health': row.health, 'outcome': row.collection_outcome, 'alert_status': row.alert_status,
        'reason': row.failure_reason, 'completeness': row.completeness, 'verification': row.verification,
        'attempted_at': row.last_attempt_at, 'last_success_at': row.last_success_at,
        'window_start': row.window_start, 'window_end': row.window_end,
        'retrieved': row.retrieved_count, 'processed': row.processed_count, 'committed': row.committed_count,
        'rejected': row.rejected_count, 'newest_event_at': row.newest_event_at,
        'newest_event_basis': row.newest_event_basis, 'duration_ms': row.duration_ms,
        'consecutive_failures': row.consecutive_failures, 'stale_after_minutes': row.stale_after_minutes,
        'window_end_complete': row.window_end_complete,
        'diagnostic': row.error if row.collection_outcome != sh.SUCCESS else '',
        'source_id': f'{row.kind}:{row.content_type_id}:{row.object_id}', 'row_id': row.pk,
    }


def _names(rows):
    """Connection names for rows, one query per connection type."""
    by_ct = {}
    for r in rows:
        by_ct.setdefault(r.content_type_id, set()).add(r.object_id)
    out = {}
    from django.contrib.contenttypes.models import ContentType
    for ct_id, ids in by_ct.items():
        model = ContentType.objects.get_for_id(ct_id).model_class()
        if model is None:
            continue
        for pk, name in model.objects.filter(pk__in=ids).values_list('pk', 'name'):
            out[(ct_id, pk)] = name
    return out


def _served_customers(rows):
    """MSP-wide RMM connections serve the customers of their devices; their
    failure counts against each of those customers."""
    from integrations.models import RMMConnection, RMMDevice
    from django.contrib.contenttypes.models import ContentType
    rmm_ct = ContentType.objects.get_for_model(RMMConnection).pk
    ids = [r.object_id for r in rows if r.organization_id is None and r.content_type_id == rmm_ct]
    served = {}
    if ids:
        for conn_id, org_id in (RMMDevice.objects.filter(connection_id__in=ids, organization__isnull=False)
                                .values_list('connection_id', 'organization_id').distinct()):
            served.setdefault((rmm_ct, conn_id), set()).add(org_id)
    return served


def gather(org_ids=None, now=None, include_msp_wide=True, kinds=None) -> list:
    """Effective health records (sh.effective applied) for the customers in
    ``org_ids`` (None = every customer). Each record carries
    ``organization_id`` and ``customers`` (the customers it counts for)."""
    from integrations.models import IntegrationSyncHealth
    now = now or timezone.now()
    want = set(kinds) if kinds else None
    stored = [k for k in MONITORING_KINDS if want is None or k in want]
    rows = list(IntegrationSyncHealth.objects.filter(kind__in=stored)) if stored else []
    names = _names(rows)
    served = _served_customers(rows)
    out = []
    for r in rows:
        f = sh.effective(fields_of(r, names.get((r.content_type_id, r.object_id), f'{r.kind} #{r.object_id}')), now)
        customers = ({r.organization_id} if r.organization_id
                     else served.get((r.content_type_id, r.object_id), set()))
        f['customers'] = customers
        out.append(f)
    if want is None or 'monitor' in want:
        out += _monitor_records(now)
    if want is None or 'push' in want:
        out += _push_records(now, polled=rows)
    if include_msp_wide and (want is None or 'pipeline' in want):
        out += _pipeline_records(now)
    _attach_coverage(out, now)
    if org_ids is None:
        return out
    allowed = set(org_ids)
    return [f for f in out if f['customers'] & allowed]


def _attach_coverage(records, now):
    """Coverage over time for every record (82.15): never breaks the page."""
    from . import coverage
    try:
        coverage.attach(records, now)
    except Exception:
        logger.warning('could not attach monitoring coverage', exc_info=True)
        for r in records:
            r.setdefault('coverage_state', coverage.NOT_VERIFIED)
            r.setdefault('coverage_window', None)
    for r in records:
        r['coverage'] = coverage.contract_block(r)


def _monitor_records(now):
    """Website monitors, derived from their own fields (no extra storage):
    a check that ran within three intervals is a verified collection; a
    monitor that is down is an alert, not a monitoring failure."""
    try:
        from monitoring.models import WebsiteMonitor
    except Exception:
        return []
    out = []
    for m in WebsiteMonitor.objects.filter(is_enabled=True).only(
            'pk', 'name', 'organization_id', 'check_interval_minutes', 'last_checked_at', 'status',
            'alert_state', 'consecutive_failures')[:2000]:
        checked = m.last_checked_at is not None
        down = m.alert_state == 'down' or m.status == 'down'
        f = {'name': m.name, 'kind': 'monitor', 'organization_id': m.organization_id, 'critical': False,
             'health': sh.HEALTHY if checked else sh.UNKNOWN,
             'outcome': sh.SUCCESS if checked else sh.NOT_ATTEMPTED,
             'alert_status': (sh.ACTIVE_ALERTS if down else sh.NO_ALERTS) if checked else sh.UNKNOWN,
             'reason': '', 'completeness': sh.COMPLETE if checked else sh.UNVERIFIED,
             'verification': sh.V_CONNECTION_TEST if checked else '', 'attempted_at': m.last_checked_at,
             'last_success_at': m.last_checked_at, 'consecutive_failures': 0,
             'stale_after_minutes': max(sh.MIN_STALE_MINUTES, (m.check_interval_minutes or 60) * 3),
             'source_id': f'monitor:{m.pk}', 'customers': {m.organization_id}}
        out.append(sh.effective(f, now))
    return out


def _push_records(now, polled=()):
    """Webhook-only security connections and SIEM endpoints. A push source
    cannot prove a quiet period: with a recent delivery it is healthy with
    alerts; without one it is unknown, never healthy / quiet. A connection that
    already has a polled health row (``polled``) is listed once, by that row."""
    try:
        from django.contrib.contenttypes.models import ContentType
        from django.db.models import Max
        from security_alerts.models import SecurityAlert, SecurityVendorConnection, SIEMWebhookEndpoint
        from security_alerts.capabilities import polls_api
    except Exception:
        return []
    conn_ct = ContentType.objects.get_for_model(SecurityVendorConnection).pk
    has_row = {r.object_id for r in polled if r.content_type_id == conn_ct}
    out = []
    last_by_conn = dict(SecurityAlert.objects.filter(connection__isnull=False).values('connection_id')
                        .annotate(m=Max('seen_at')).values_list('connection_id', 'm'))
    last_by_siem = dict(SecurityAlert.objects.filter(siem_endpoint__isnull=False).values('siem_endpoint_id')
                        .annotate(m=Max('seen_at')).values_list('siem_endpoint_id', 'm'))
    sources = [(c, last_by_conn.get(c.pk), f'push:conn:{c.pk}', customer_of(c))
               for c in SecurityVendorConnection.objects.filter(is_active=True)
               if not polls_api(c.provider) and c.pk not in has_row]
    sources += [(e, last_by_siem.get(e.pk), f'push:siem:{e.pk}', customer_of(e))
                for e in SIEMWebhookEndpoint.objects.filter(is_active=True)]
    for obj, last, sid, org_id in sources:
        f = {'name': obj.name, 'kind': 'push', 'organization_id': org_id, 'critical': True,
             'health': sh.HEALTHY if last else sh.UNKNOWN, 'outcome': sh.SUCCESS if last else sh.NOT_ATTEMPTED,
             'alert_status': sh.ACTIVE_ALERTS if last else sh.UNKNOWN, 'reason': '',
             'completeness': sh.COMPLETE if last else sh.UNVERIFIED, 'verification': sh.V_PUSH,
             'attempted_at': last, 'last_success_at': last, 'newest_event_at': last, 'consecutive_failures': 0,
             'stale_after_minutes': 24 * 60, 'source_id': sid, 'customers': {org_id} if org_id else set()}
        f = sh.effective(f, now)
        if f['health'] != sh.HEALTHY and f.get('outcome') != sh.NOT_ATTEMPTED:
            # No delivery inside the window: unknown (push cannot confirm
            # quiet), not stale-as-failure.
            f.update(health=sh.UNKNOWN, reason='', alert_status=sh.UNKNOWN)
        out.append(f)
    return out


def _pipeline_records(now):
    """The shared event pipeline's own ingestion health (82.5), MSP-wide."""
    from . import models as M
    out = []
    for h in M.SourceHealth.objects.all():
        failing = h.consecutive_failures
        f = {'name': f'Event pipeline: {h.get_source_display()}', 'kind': 'pipeline', 'organization_id': None,
             'critical': False,
             'health': (sh.FAILED if failing >= sh.PERSISTENT_AFTER else sh.DEGRADED if failing
                        else sh.HEALTHY if h.last_success_at else sh.UNKNOWN),
             'outcome': sh.FAILED if failing else sh.SUCCESS if h.last_success_at else sh.NOT_ATTEMPTED,
             'alert_status': sh.UNKNOWN, 'reason': sh.INGESTION_FAILED if failing else '',
             'completeness': sh.COMPLETE if h.last_success_at and not failing else sh.UNVERIFIED,
             'attempted_at': h.last_run_at, 'last_success_at': h.last_success_at,
             'consecutive_failures': failing, 'stale_after_minutes': 30, 'source_id': f'pipeline:{h.source}',
             'customers': set()}
        f = sh.effective(f, now)
        if f['health'] == sh.HEALTHY:
            f['alert_status'] = sh.NO_ALERTS   # the pipeline carries no alerts of its own
        out.append(f)
    return out


def by_customer(records, org_names):
    """[(org_id, name, summary, records)] worst first, then name."""
    groups = {}
    for f in records:
        for org_id in f['customers']:
            groups.setdefault(org_id, []).append(f)
    out = [(org_id, org_names.get(org_id, f'Customer #{org_id}'), sh.summarize(rs), rs)
           for org_id, rs in groups.items()]
    out.sort(key=lambda t: (-(t[2]['worst'].rank if t[2]['worst'] else 0), t[1].lower()))
    return out


def summary_for(org_ids, kinds=None, now=None):
    """One summary for a set of customers (None = all), optionally only some
    kinds. Used by the dashboards, the digest and the AI context."""
    return sh.summarize(gather(org_ids, now=now, include_msp_wide=False, kinds=kinds))


# --- transitions, notifications and the freshness sweep -------------------------------------

def _transition(row, f, now):
    """Audit every display-state change; notify technicians of persistent
    failures of a critical source and of its recovery, once each."""
    from integrations.models import IntegrationSyncHealth as H
    f = sh.effective(f, now)
    d = sh.display(f)
    old = row.display_state
    if d.key == old:
        return
    if not H.objects.filter(pk=row.pk, display_state=old).update(display_state=d.key, state_changed_at=now):
        return      # another worker recorded it
    row.display_state, row.state_changed_at = d.key, now
    _audit(row, f, old, d)
    persistent = d.key in ALERTING and (f['health'] == sh.FAILED or d.key == sh.D_STALE)
    if persistent and row.critical and row.alerted_state != d.key:
        H.objects.filter(pk=row.pk).update(alerted_state=d.key)
        row.alerted_state = d.key
        notify(row, f, d)
    elif d.key in (sh.D_HEALTHY_QUIET, sh.D_HEALTHY_ACTIVE) and row.alerted_state:
        was = row.alerted_state
        if H.objects.filter(pk=row.pk, alerted_state=was).update(alerted_state=''):
            row.alerted_state = ''
            notify(row, f, d, recovered_from=was)


def _audit(row, f, old, d):
    try:
        from audit.models import AuditLog
        from core.models import Organization
        name = f.get('name') or row.kind
        before = sh.DISPLAY[old][0] if old in sh.DISPLAY else 'not recorded'
        AuditLog.log(user=None, action='update',
                     organization=Organization.objects.filter(pk=row.organization_id).first()
                     if row.organization_id else None,
                     object_type='monitoring_source_health', object_id=row.pk, object_repr=name[:200],
                     description=f'Monitoring source "{name}": {before} -> {d.label}',
                     extra_data={'event': 'monitoring_source_health', 'kind': row.kind, 'from': old, 'to': d.key,
                                 'health': f['health'], 'outcome': f['outcome'], 'reason': f['reason'],
                                 'consecutive_failures': f['consecutive_failures']})
    except Exception:
        logger.warning('could not audit a source health transition', exc_info=True)


def warning_id(row_id, key, now=None):
    slot = int((now or timezone.now()).timestamp() // NOTIFY_WINDOW.total_seconds())
    return f'srchealth:{row_id}:{key}:{slot}'[:200]


def notify(row, f, d, recovered_from='') -> bool:
    """At most one e-mail per (source, state) per 30 minutes, across workers
    (the same SystemWarningNotification marker Connect uses)."""
    from core.models import SystemWarningNotification
    now = timezone.now()
    prefix = f'srchealth:{row.pk}:{d.key}:'
    name = f.get('name') or KIND_LABELS.get(row.kind, row.kind)
    title = (f'Monitoring source "{name}" recovered ({d.label})' if recovered_from
             else f'Monitoring source "{name}": {d.label}')
    try:
        if SystemWarningNotification.objects.filter(warning_id__startswith=prefix,
                                                    notified_at__gte=now - NOTIFY_WINDOW).exists():
            return False
        _, created = SystemWarningNotification.objects.get_or_create(
            warning_id=warning_id(row.pk, d.key, now),
            defaults={'severity': 'info' if recovered_from else 'high', 'title': title[:200]})
    except Exception:
        logger.warning('could not record a source health notification marker', exc_info=True)
        return False
    if not created:
        return False
    body = '\n'.join([
        title + '.', '',
        (f'It was {sh.DISPLAY.get(recovered_from, (recovered_from,))[0]} before; collection is verified again.'
         if recovered_from else d.tooltip),
        '' if recovered_from else ('Until it is fixed, a quiet dashboard for this source does not mean the '
                                   'customer is healthy.'),
        f'Last successful collection: {f["last_success_at"]:%Y-%m-%d %H:%M} UTC' if f.get('last_success_at')
        else 'Last successful collection: never',
        '', 'You get at most one of these per source and state every 30 minutes.'])
    wid = warning_id(row.pk, d.key, now)
    transaction.on_commit(lambda: threading.Thread(target=_send, args=(title, body, wid), daemon=True).start())
    return True


def _send(title, body, wid):
    from django.db import close_old_connections
    try:
        from core.mailer import (brand_name, default_from_email, get_smtp_connection, notification_recipients,
                                 send_to_recipients, site_url)
        from core.models import SystemSetting, SystemWarningNotification
        settings = SystemSetting.get_settings()
        if not settings.smtp_enabled or not settings.smtp_host:
            return
        recipients = notification_recipients()
        connection = get_smtp_connection(settings) if recipients else None
        if connection is None:
            return
        sent = send_to_recipients(connection, default_from_email(settings), recipients,
                                  f'[{brand_name(settings)}] {title}',
                                  body + f'\n\nMonitoring reliability: {site_url(settings)}/security/events/sources/')
        SystemWarningNotification.objects.filter(warning_id=wid).update(recipients_count=sent or 0)
    except Exception:
        logger.warning('could not send a source health notification', exc_info=True)
    finally:
        close_old_connections()


def sweep(now=None) -> int:
    """Re-evaluate stored rows against their freshness threshold (a
    collector that stopped running writes nothing, so only a sweep can see
    it go stale). Runs from events_tick. Returns transitions recorded."""
    from integrations.models import IntegrationSyncHealth
    now = now or timezone.now()
    rows = list(IntegrationSyncHealth.objects.filter(kind__in=MONITORING_KINDS))
    names = _names(rows)
    changed = 0
    from . import coverage
    for row in rows:
        f = fields_of(row, names.get((row.content_type_id, row.object_id), ''))
        before = row.display_state
        _transition(row, f, now)
        changed += row.display_state != before
        e = sh.effective(f, now)
        if e.get('freshness') == sh.STALE and row.last_success_at and e.get('outcome') != sh.FAILED:
            # A collector that stopped writing: its silence is a gap too.
            try:
                coverage.open_for_stale(row, f, now)
            except Exception:
                logger.warning('could not open a coverage gap for a stale source', exc_info=True)
    return changed


def system_warnings():
    """For core.system_warnings: critical monitoring sources that failed
    persistently or went stale."""
    from integrations.models import IntegrationSyncHealth
    rows = list(IntegrationSyncHealth.objects.filter(kind__in=MONITORING_KINDS, critical=True)
                .exclude(alerted_state='').order_by('-state_changed_at')[:20])
    names = _names(rows)
    out = []
    for r in rows:
        label = sh.DISPLAY.get(r.alerted_state, (r.alerted_state,))[0]
        name = names.get((r.content_type_id, r.object_id), f'{r.kind} #{r.object_id}')
        out.append({
            'id': f'srchealth:{r.pk}:{r.alerted_state}', 'severity': 'high', 'category': 'monitoring',
            'title': f'Monitoring source "{name}": {label}',
            'detail': 'Alerts from this source cannot be trusted to be complete until collection works again.',
            'action_url': '/security/events/sources/', 'action_label': 'Monitoring reliability',
            'source_date': r.state_changed_at,
        })
    return out
