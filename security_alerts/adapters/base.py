"""
Per-vendor security adapters. Inherit SecurityProvider, register via
the existing integrations.sdk.registry.@register decorator (slug
prefix 'security_').

Each adapter implements:
- test_connection(connection) -> {ok, message}
- poll_alerts(connection, since=None) -> list of normalized alert dicts
- (optional) webhook_handler(connection, request) -> normalized alerts
"""
from abc import abstractmethod
from integrations.sdk.base import IntegrationProvider
from security_alerts.siem import _bucket_severity


class SecurityProvider(IntegrationProvider):
    """Abstract base — Phase 9 vendor adapter.

    Monitoring health contract (roadmap 82.8, docs/standards/
    MONITORING_HEALTH_STANDARD.md §5):

    * ``poll_alerts`` must RAISE on an HTTP error, a refused permission or a
      malformed response. Returning ``[]`` means "the query succeeded and the
      window is empty", nothing else. Set ``health_reason`` on the exception
      (or let ``events.source_health.classify_exception`` read the HTTP
      status and Retry-After) — never swallow it.
    * ``supports_empty_window_probe`` + ``probe_empty_window()``: when a
      window comes back empty, a bounded, read-only, tenant-scoped probe
      (one record, no filter beyond the tenant) confirms the query really
      could have returned data. A failed or forbidden probe fails the read.
      Without a probe an empty window is recorded as unverified, never as
      healthy / quiet.
    * ``ordering_guaranteed``: True only if the vendor documents newest-first
      ordering; otherwise the newest event is the maximum validated
      ``occurred_at``, or unknown.
    """

    supports_empty_window_probe = False
    ordering_guaranteed = False
    # Monitoring coverage (82.15–82.20): what the vendor lets us ask for
    # after an outage. None = not declared, so a missed window is never
    # reported as fully recovered. An adapter that can page through past
    # alerts declares an ``events.coverage.HistoryCapability`` (history
    # support, maximum lookback, ordering, completeness signal) and
    # implements ``fetch_history``.
    history_capability = None

    @abstractmethod
    def poll_alerts(self, connection, since=None):
        """Return a list of dicts: [{external_id, severity, title,
        description, asset_hint, raw_payload, occurred_at}, ...]"""

    def probe_empty_window(self, connection, window_start, window_end):
        """Bounded verification probe for an empty window. Return True when
        the source answered (it could have returned data); raise on any
        failure. Read-only, at most one small request."""
        raise NotImplementedError

    def fetch_history(self, connection, start, end, page_token=None, limit=100):
        """One page of alerts that occurred in [start, end), as an
        ``events.coverage.HistoryPage`` of the same dicts poll_alerts
        returns (with ``occurred_at``). Raise on any failure; never return
        an empty page for an error. Read-only, bounded timeout."""
        raise NotImplementedError

    def sync(self, connection):
        """Poll + persist normalized alerts, and record the collection
        against the monitoring health contract."""
        import time
        from django.utils import timezone
        from events import source_health as sh
        from events.source_health_store import cursor, record_collection

        started = timezone.now()
        clock = time.monotonic()
        # The window starts where the last *complete* collection ended; a
        # failed or partial attempt never advances it, so nothing in its
        # window is skipped. Legacy fallback: last_sync_at after an ok run.
        since = cursor(connection, 'security')
        if since is None and connection.last_sync_status == 'ok':
            since = connection.last_sync_at

        def finish(result, ok_status, error_text):
            result.duration_ms = int((time.monotonic() - clock) * 1000)
            record_collection(connection, 'security', result, legacy_status=True)
            connection.last_sync_at = started
            connection.last_sync_status = ok_status
            connection.last_error = error_text[:1000]
            connection.save(update_fields=['last_sync_status', 'last_error', 'last_sync_at'])

        try:
            alerts = self.poll_alerts(connection, since=since)
            if alerts is None or not isinstance(alerts, (list, tuple)):
                raise _InvalidResponse('The adapter returned no alert list.')
        except Exception as exc:
            from integrations.health import redact_for
            message = redact_for(connection, exc)
            finish(sh.CollectionResult(attempted_at=started, window_start=since, window_end=started, error=exc,
                                       diagnostic=message), 'error', message)
            return {'ok': False, 'records_imported': 0, 'errors': [message]}

        verification = ''
        if not alerts:
            if self.supports_empty_window_probe:
                try:
                    if not self.probe_empty_window(connection, since, started):
                        raise _InvalidResponse('The verification probe did not confirm the window.')
                    verification = sh.V_PROBE
                except Exception as exc:
                    from integrations.health import redact_for
                    message = redact_for(connection, exc)
                    finish(sh.CollectionResult(attempted_at=started, window_start=since, window_end=started,
                                               error=exc, diagnostic=f'Empty window, probe failed: {message}'),
                           'error', message)
                    return {'ok': False, 'records_imported': 0, 'errors': [message]}
            else:
                verification = sh.V_NOT_SUPPORTED

        imported, committed, rejected, errors = 0, 0, 0, []
        # An open coverage gap: alerts first stored by this read happened
        # while nobody could see them (82.16).
        from events import coverage
        window = coverage.open_window(connection, 'security')
        late = dups = 0
        max_delay = None
        for a in alerts:
            try:
                if not isinstance(a, dict):
                    raise _InvalidResponse('alert is not an object')
                out = ingest_polled_alert(connection, a, window=window)
            except Exception as exc:
                rejected += 1
                if len(errors) < 5:
                    errors.append(f'{type(exc).__name__}')
                continue
            committed += 1
            if out['created']:
                imported += 1
                if out['late']:
                    late += 1
                    if out['delay'] is not None:
                        max_delay = out['delay'] if max_delay is None else max(max_delay, out['delay'])
            elif window is not None:
                dups += 1
        coverage.note_delivered(window, late=late, duplicates=dups, rejected=rejected if window else 0,
                                max_delay=max_delay)

        from security_alerts.models import SecurityAlert
        open_alerts = SecurityAlert.objects.filter(connection=connection, status__in=('new', 'acknowledged')).count()
        result = sh.CollectionResult(
            attempted_at=started, window_start=since, window_end=started, retrieved=len(alerts),
            processed=len(alerts), committed=committed, rejected=rejected, verification=verification,
            event_times=[a.get('occurred_at') for a in alerts if isinstance(a, dict)],
            ordering_guaranteed=self.ordering_guaranteed, open_alerts=open_alerts,
            diagnostic=(f'{rejected} of {len(alerts)} alerts could not be stored ({", ".join(errors)})'
                        if rejected else ''))
        if rejected:
            finish(result, 'partial' if committed else 'error', result.diagnostic)
        else:
            finish(result, 'ok', '')
        return {'ok': not rejected, 'records_imported': imported, 'errors': [result.diagnostic] if rejected else []}


class _InvalidResponse(ValueError):
    health_reason = 'invalid_response'


def ingest_polled_alert(connection, a, *, window=None, via_backfill=False):
    """Store one polled alert through the normal path: deduplicated by
    (connection, external id), then the alert-to-ticket rules and incident
    correlation (whose playbooks keep their approval rules). Used by the
    regular poll and by the backfill alike, so a backfilled alert gets no
    shortcut. Returns {'alert', 'created', 'late', 'delay'}.

    The vendor's event time is kept as ``occurred_at`` (validated; else
    empty) and the delay to ``seen_at`` recorded. A new alert that happened
    inside an open coverage gap is marked delivered late, and so are its
    ticket and incident.
    """
    from django.utils import timezone
    from events import coverage
    from security_alerts.ingest import upsert_alert
    now = timezone.now()
    occurred = coverage.valid_event_time(a.get('occurred_at'), now)
    late = coverage.is_late(window, occurred, now, via_backfill=via_backfill)
    delay = coverage.delay_seconds(occurred, now)
    obj, created = upsert_alert(
        {'connection': connection, 'external_id': a.get('external_id', '')},
        {
            'organization': connection.organization,
            'client_org': connection.client_org,
            'severity': _bucket_severity(a.get('severity')),
            'title': (a.get('title') or '')[:300],
            'description': a.get('description', ''),
            'asset_hint': (a.get('asset_hint') or '')[:200],
            'raw_payload': a.get('raw_payload', {}),
        },
        create_only={'occurred_at': occurred, 'delivery_delay_seconds': delay, 'delivered_late': late,
                     'coverage_window_id': window.pk if (late and window is not None) else None},
    )
    if created:
        # Auto-ticket evaluation
        _maybe_auto_ticket(obj)
        # Phase 23 v3.17.338 — auto-correlate into a SecurityIncident
        try:
            from security_alerts.models import _correlate_alert_to_incident
            incident = _correlate_alert_to_incident(obj)
            if late and incident is not None:
                incident.add_event(kind='delivered_late', alert=obj, message=late_note(obj))
        except Exception:
            pass
    return {'alert': obj, 'created': created, 'late': bool(created and late), 'delay': delay if created else None}


def late_note(alert):
    from events.coverage import format_delay
    when = f'{alert.occurred_at:%Y-%m-%d %H:%M} UTC' if alert.occurred_at else 'an unknown time'
    return (f'Delivered late: alert {alert.pk} occurred at {when} and was received at '
            f'{alert.seen_at:%Y-%m-%d %H:%M} UTC (delay {format_delay(alert.delivery_delay_seconds)}), after a '
            f'monitoring coverage gap. It was not seen in real time.')


# SR-08: an alert matching an open auto-ticket for the same customer, asset
# and title (within the window) joins that ticket instead of opening another,
# and one source opens at most AUTO_TICKET_HOURLY_CAP tickets an hour; past
# the cap alerts are still stored, no tickets are opened, and the audit log
# records it once an hour.
AUTO_TICKET_DEDUP_HOURS = 24
AUTO_TICKET_HOURLY_CAP = 20


def _open_duplicate_ticket(alert):
    from datetime import timedelta
    from django.utils import timezone
    from security_alerts.models import SecurityAlert
    twin = (SecurityAlert.objects
            .filter(organization=alert.organization, client_org=alert.client_org,
                    asset_hint__iexact=alert.asset_hint, title__iexact=alert.title.strip(),
                    auto_ticket__isnull=False, auto_ticket__status__is_terminal=False,
                    seen_at__gte=timezone.now() - timedelta(hours=AUTO_TICKET_DEDUP_HOURS))
            .exclude(pk=alert.pk).select_related('auto_ticket').order_by('-seen_at').first())
    return twin.auto_ticket if twin else None


def _source_filter(alert):
    if alert.connection_id:
        return {'connection_id': alert.connection_id}
    if alert.siem_endpoint_id:
        return {'siem_endpoint_id': alert.siem_endpoint_id}
    return None


def _over_hourly_cap(alert):
    from datetime import timedelta
    from django.utils import timezone
    from security_alerts.models import SecurityAlert
    source = _source_filter(alert)
    if source is None:
        return False
    recent = SecurityAlert.objects.filter(
        **source, auto_ticket__isnull=False,
        auto_ticket__created_at__gte=timezone.now() - timedelta(hours=1)).values('auto_ticket').distinct().count()
    return recent >= AUTO_TICKET_HOURLY_CAP


def _note_cap_reached(alert):
    from django.core.cache import cache
    source = _source_filter(alert)
    key = 'security_alerts:autoticket_cap:' + ':'.join(f'{k}={v}' for k, v in source.items())
    if not cache.add(key, 1, 3600):
        return
    from audit.models import AuditLog
    import logging
    logging.getLogger('security_alerts').warning('auto-ticket cap reached for %s', source)
    AuditLog.log(
        user=None, action='update', organization=alert.organization,
        object_type='security_alerts.SecurityAlert', object_id=alert.pk, object_repr=alert.title[:200],
        description=(f'Auto-ticket limit reached: this source opened {AUTO_TICKET_HOURLY_CAP} tickets in the last '
                     f'hour. Alerts are still recorded; no more tickets this hour.'),
        extra_data={'event': 'security_auto_ticket_cap', **source},
    )


def _maybe_auto_ticket(alert):
    """Evaluate active SecurityAlertRule rows; create a ticket if any matches."""
    from security_alerts.models import SecurityAlertRule
    from django.utils import timezone

    rules = SecurityAlertRule.objects.filter(
        organization=alert.organization, is_active=True,
    ).order_by('priority', 'pk')

    severity_rank = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
    for rule in rules:
        conn = alert.connection  # None for SIEM alerts
        if rule.match_provider and (conn is None or rule.match_provider != conn.provider):
            continue
        if rule.match_category and (conn is None or rule.match_category != conn.category):
            continue
        if rule.match_client_org_id and rule.match_client_org_id != alert.client_org_id:
            continue
        if rule.match_severity_min:
            if severity_rank.get(alert.severity, 0) < severity_rank.get(rule.match_severity_min, 0):
                continue
        # Suppression window
        if rule.suppress_start_hour is not None and rule.suppress_end_hour is not None:
            now_hr = timezone.now().hour
            in_window = (
                rule.suppress_start_hour <= now_hr <= rule.suppress_end_hour
                if rule.suppress_start_hour <= rule.suppress_end_hour
                else (now_hr >= rule.suppress_start_hour or now_hr <= rule.suppress_end_hour)
            )
            if in_window:
                continue
        # Match. Join an open ticket for the same alert, or stop at the cap.
        existing = _open_duplicate_ticket(alert)
        if existing is not None:
            alert.auto_ticket = existing
            alert.save(update_fields=['auto_ticket'])
            return
        if _over_hourly_cap(alert):
            _note_cap_reached(alert)
            return
        try:
            from psa.models import Ticket, Queue, TicketPriority, TicketStatus, TicketType
            queue = (Queue.objects.filter(pk=rule.ticket_queue_id).first()
                     if rule.ticket_queue_id else Queue.objects.filter(is_active=True).first())
            priority_code = rule.ticket_priority_code or {
                'critical': 'P1', 'high': 'P2', 'medium': 'P3',
                'low': 'P4', 'info': 'P5',
            }.get(alert.severity, 'P3')
            priority = TicketPriority.objects.filter(code=priority_code).first() or TicketPriority.objects.first()
            status = TicketStatus.objects.filter(slug='new').first()
            ttype = TicketType.objects.first()
            late = getattr(alert, 'delivered_late', False)
            ticket = Ticket.objects.create(
                organization=alert.client_org or alert.organization,
                subject=(f'[Security][Delivered late] {alert.title[:185]}' if late
                         else f'[Security] {alert.title[:200]}'),
                description=(f'{late_note(alert)}\n\n{alert.description or ""}'.strip() if late
                             else alert.description or ''),
                queue=queue, priority=priority, status=status, ticket_type=ttype,
                assigned_to=rule.ticket_assignee,
                source='monitoring',
            )
            alert.auto_ticket = ticket
            alert.save(update_fields=['auto_ticket'])
            return  # only fire the highest-priority matching rule
        except Exception:
            import logging
            logging.getLogger('security_alerts').exception('auto-ticket creation failed')
            return
