"""Source adapters: turn one source row into the normalized envelope.

Each adapter answers three questions for the projection engine:

* ``load(pk)``           – the source row, or None if it is gone;
* ``envelope(obj)``      – the OperationalEvent fields (plus ``dedup_key``);
* ``links(obj)``         – (ticket ids, incident ids) the source already records.

``new_rows(after_pk, limit)`` lets the backstop scan find rows created without
a save signal (bulk inserts). Adapters never write to the source.
"""
import json

from django.utils import timezone

from . import models as M


def _cap_raw(data):
    """Keep the raw payload only up to RAW_MAX_BYTES; otherwise a marker."""
    if not data:
        return {}
    try:
        text = json.dumps(data, default=str)
    except (TypeError, ValueError):
        return {'_omitted': 'not serializable'}
    if len(text.encode()) <= M.RAW_MAX_BYTES:
        return data if isinstance(data, dict) else {'value': data}
    return {'_truncated': True, '_original_bytes': len(text.encode()),
            'head': text[:M.RAW_MAX_BYTES // 2]}


class Adapter:
    source = ''
    model = None
    select = ()

    def load(self, pk):
        return self.model.objects.select_related(*self.select).filter(pk=pk).first()

    def new_rows(self, after_pk, limit):
        return list(self.model.objects.filter(pk__gt=after_pk).order_by('pk').values_list('pk', flat=True)[:limit])

    def links(self, obj):
        return set(), set()


class SecurityAlertAdapter(Adapter):
    source = M.SOURCE_SECURITY
    select = ('connection', 'siem_endpoint', 'client_org', 'organization')
    STATUS = {'new': M.STATUS_OPEN, 'acknowledged': M.STATUS_ACK, 'resolved': M.STATUS_RESOLVED,
              'dismissed': M.STATUS_SUPPRESSED}

    @property
    def model(self):
        from security_alerts.models import SecurityAlert
        return SecurityAlert

    def envelope(self, a):
        via = a.connection or a.siem_endpoint
        raw = a.raw_payload if isinstance(a.raw_payload, dict) else {}
        return {
            # One install serves one MSP: the customer is the pinned client
            # when there is one, otherwise the alert's organization.
            'organization_id': a.client_org_id or a.organization_id,
            'connection_label': (f'{via.name}' if via else '')[:160],
            'vendor_event_id': a.external_id[:200],
            'event_type': (a.connection.get_provider_display() if a.connection
                           else 'SIEM webhook' if a.siem_endpoint else 'security alert')[:120],
            'title': a.title[:300] or 'Security alert',
            'severity': a.severity if a.severity in M.SEVERITY_RANK else 'medium',
            'source_severity': a.severity,
            'status': self.STATUS.get(a.status, M.STATUS_OPEN),
            'source_status': a.status,
            'first_seen_at': a.seen_at,
            'last_seen_at': a.acknowledged_at and max(a.acknowledged_at, a.seen_at) or a.seen_at,
            'resolved_at': a.resolved_at,
            'asset_hint': a.asset_hint[:200],
            'mitre_techniques': _list(raw.get('mitre') or raw.get('mitre_techniques') or raw.get('techniques')),
            'raw': _cap_raw(a.raw_payload),
            'dedup_key': f'security:{a.pk}',
            'correlation_group': _group(a.client_org_id or a.organization_id, a.asset_hint),
        }

    def links(self, a):
        return ({a.auto_ticket_id} if a.auto_ticket_id else set(),
                set(a.incidents.values_list('pk', flat=True)))


class RMMAlertAdapter(Adapter):
    source = M.SOURCE_RMM
    select = ('connection', 'device')
    SEVERITY = {'critical': 'critical', 'error': 'high', 'warning': 'medium', 'info': 'info'}
    STATUS = {'active': M.STATUS_OPEN, 'acknowledged': M.STATUS_ACK, 'resolved': M.STATUS_RESOLVED,
              'closed': M.STATUS_RESOLVED}

    @property
    def model(self):
        from integrations.models import RMMAlert
        return RMMAlert

    def envelope(self, a):
        device = a.device
        return {
            'organization_id': a.organization_id,
            'connection_label': a.connection.name[:160],
            'vendor_event_id': a.external_id[:200],
            'event_type': a.alert_type[:120],
            'title': (a.message or a.alert_type or 'RMM alert').splitlines()[0][:300],
            'severity': self.SEVERITY.get(a.severity, 'medium'),
            'source_severity': a.severity,
            'status': self.STATUS.get(a.status, M.STATUS_OPEN),
            'source_status': a.status,
            'first_seen_at': a.triggered_at,
            'last_seen_at': a.resolved_at or a.triggered_at,
            'resolved_at': a.resolved_at,
            'asset_id': device.linked_asset_id if device else None,
            'asset_hint': (device.device_name if device else '')[:200],
            'raw': _cap_raw(a.raw_data),
            'dedup_key': f'rmm:{a.pk}',
            'correlation_group': _group(a.organization_id, device.device_name if device else ''),
        }


class Rem0teAdapter(Adapter):
    source = M.SOURCE_REM0TE
    select = ('connection',)
    SEVERITY = {'critical': 'critical', 'warning': 'medium', 'info': 'info'}
    STATUS = {'resolved': M.STATUS_RESOLVED, 'acknowledged': M.STATUS_ACK}

    @property
    def model(self):
        from psa_ai.models import Rem0teAlertTicket
        return Rem0teAlertTicket

    def envelope(self, r):
        return {
            'organization_id': r.organization_id,
            'connection_label': r.connection_label[:160],
            'vendor_event_id': r.alert_id[:200],
            'event_type': r.kind[:120],
            'title': r.title[:300] or r.kind or 'Rem0te alert',
            'severity': self.SEVERITY.get(r.severity, 'medium'),
            'source_severity': r.severity,
            'status': self.STATUS.get(r.state, M.STATUS_OPEN),
            'source_status': r.state,
            'first_seen_at': r.created_at,
            'last_seen_at': r.updated_at,
            'resolved_at': r.resolved_at,
            'asset_hint': r.computer_name[:200],
            'raw': _cap_raw(r.patch_summary),
            'dedup_key': f'rem0te:{r.pk}',
            'correlation_group': _group(r.organization_id, r.computer_name),
        }

    def links(self, r):
        return ({r.ticket_id} if r.ticket_id else set()), set()


class BackupAlertAdapter(Adapter):
    source = M.SOURCE_BACKUP
    select = ('connection', 'system')
    STATUS = {'open': M.STATUS_OPEN, 'acknowledged': M.STATUS_ACK, 'resolved': M.STATUS_RESOLVED}

    @property
    def model(self):
        from backup_monitoring.models import BackupAlert
        return BackupAlert

    def envelope(self, b):
        system = b.system
        hint = system.name if system else ''
        return {
            'organization_id': b.organization_id,
            'connection_label': b.connection.name[:160],
            'vendor_event_id': b.dedup_key[:200],
            'event_type': f'backup {b.kind}'[:120],
            'title': b.title[:300] or f'Backup {b.kind}',
            'severity': 'critical' if b.severity == 'critical' else 'medium',
            'source_severity': b.severity,
            'status': self.STATUS.get(b.status, M.STATUS_OPEN),
            'source_status': b.status,
            'first_seen_at': b.first_seen_at,
            'last_seen_at': b.last_seen_at,
            'resolved_at': b.resolved_at,
            'occurrences': b.occurrences or 1,
            'asset_id': getattr(system, 'asset_id', None) if system else None,
            'asset_hint': str(hint)[:200],
            'dedup_key': f'backup:{b.pk}',
            'correlation_group': _group(b.organization_id, hint),
        }

    def links(self, b):
        return ({b.ticket_id} if b.ticket_id else set()), set()


class MonitorAdapter(Adapter):
    """Website monitors have no outage rows: each down period (alert_state
    'down' until 'up') becomes one event. ``source_id`` is the monitor."""
    source = M.SOURCE_MONITOR

    @property
    def model(self):
        from monitoring.models import WebsiteMonitor
        return WebsiteMonitor

    def new_rows(self, after_pk, limit):
        # Monitors are long-lived; the scan looks for ones that are down
        # without a live event instead of new rows (see projection.scan).
        return []


class ConnectAdapter(Adapter):
    """Agit8or Connect connection incidents (connect.ConnectIncident; Quick
    Connect increment E). One event per incident: every status change of the
    connection while the incident lasts updates it (severity, title,
    occurrences = status changes), recovery resolves it. MSP-wide (no
    customer): a connection belongs to the installation. Names, statuses and
    failure codes only."""
    source = M.SOURCE_CONNECT
    select = ('connection',)
    SEVERITY = {'security_blocked': 'critical', 'offline': 'high', 'suspended': 'high', 'degraded': 'medium',
                'revoked': 'medium', 'connected': 'info'}

    @property
    def model(self):
        from connect.models import ConnectIncident
        return ConnectIncident

    def envelope(self, i):
        from connect import status as st
        conn = i.connection
        name = (conn.remote_display_name or conn.remote_app_type or str(conn.pk))[:120]
        label = st.LABELS.get(i.status, i.status)
        return {
            'organization_id': None,
            'connection_label': name[:160],
            'vendor_event_id': f'{conn.pk}:{i.pk}'[:200],
            'event_type': f'connected application {label.lower()}'[:120],
            'title': (f'Connected application "{name}" is {label}' if i.is_open else
                      f'Connected application "{name}" recovered')[:300],
            'severity': self.SEVERITY.get(i.worst_status if i.is_open else 'connected', 'medium'),
            'source_severity': i.status,
            'status': M.STATUS_OPEN if i.is_open else M.STATUS_RESOLVED,
            'source_status': i.status if i.is_open else (i.resolution or 'resolved'),
            'first_seen_at': i.opened_at,
            'last_seen_at': i.resolved_at or i.updated_at,
            'resolved_at': i.resolved_at,
            'occurrences': max(i.transition_count, 1),
            'asset_hint': '',
            'raw': _cap_raw({'connection': str(conn.pk), 'app_type': conn.remote_app_type, 'status': i.status,
                             'worst_status': i.worst_status, 'code': i.code, 'muted': i.muted,
                             'transitions': list(i.transitions or [])[-20:]}),
            'dedup_key': f'connect:{conn.pk}:{i.pk}',
            'correlation_group': '',
        }

    def links(self, i):
        return ({i.ticket_id} if i.ticket_id else set()), set()


ADAPTERS = {a.source: a for a in (SecurityAlertAdapter(), RMMAlertAdapter(), Rem0teAdapter(),
                                  BackupAlertAdapter(), MonitorAdapter(), ConnectAdapter())}


def _list(value):
    if not value:
        return []
    if isinstance(value, str):
        value = [v.strip() for v in value.split(',')]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v)[:40] for v in value if v][:20]


def _group(org_id, hint):
    """Coarse correlation group: same customer and same host / asset hint."""
    hint = (hint or '').strip().lower()
    if not hint:
        return ''
    return f'{org_id or 0}:{hint}'[:120]


def now():
    return timezone.now()
