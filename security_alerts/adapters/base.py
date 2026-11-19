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
            obj, created = SecurityAlert.objects.update_or_create(
                connection=connection,
                external_id=a.get('external_id', ''),
                defaults={
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


def _maybe_auto_ticket(alert):
    """Evaluate active SecurityAlertRule rows; create a ticket if any matches."""
    from security_alerts.models import SecurityAlertRule
    from django.utils import timezone

    rules = SecurityAlertRule.objects.filter(
        organization=alert.organization, is_active=True,
    ).order_by('priority', 'pk')

    severity_rank = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
    for rule in rules:
        if rule.match_provider and rule.match_provider != alert.connection.provider:
            continue
        if rule.match_category and rule.match_category != alert.connection.category:
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
        # Match — create ticket
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
