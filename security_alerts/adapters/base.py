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
    """Abstract base — Phase 9 vendor adapter."""

    @abstractmethod
    def poll_alerts(self, connection, since=None):
        """Return a list of dicts: [{external_id, severity, title,
        description, asset_hint, raw_payload, occurred_at}, ...]"""

    def sync(self, connection):
        """Default sync: poll + persist normalized alerts."""
        from security_alerts.models import SecurityAlert
        from django.utils import timezone

        try:
            since = connection.last_sync_at
            alerts = self.poll_alerts(connection, since=since)
        except Exception as exc:
            connection.last_sync_status = 'error'
            connection.last_error = str(exc)[:1000]
            connection.last_sync_at = timezone.now()
            connection.save(update_fields=['last_sync_status', 'last_error', 'last_sync_at'])
            return {'ok': False, 'records_imported': 0, 'errors': [str(exc)]}

        imported = 0
        for a in alerts:
            from security_alerts.ingest import upsert_alert
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
            )
            if created:
                imported += 1
                # Auto-ticket evaluation
                _maybe_auto_ticket(obj)
                # Phase 23 v3.17.338 — auto-correlate into a SecurityIncident
                try:
                    from security_alerts.models import _correlate_alert_to_incident
                    _correlate_alert_to_incident(obj)
                except Exception:
                    pass

        connection.last_sync_at = timezone.now()
        connection.last_sync_status = 'ok'
        connection.last_error = ''
        connection.save(update_fields=['last_sync_at', 'last_sync_status', 'last_error'])
        return {'ok': True, 'records_imported': imported, 'errors': []}


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
            ticket = Ticket.objects.create(
                organization=alert.client_org or alert.organization,
                subject=f'[Security] {alert.title[:200]}',
                description=alert.description or '',
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
