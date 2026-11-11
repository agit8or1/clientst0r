"""Alert → ticket policy (optional; off by default).

Takes a monitoring alert — a signed Rem0te alert event, or an alert that
another RMM provider synced — and decides, by data an administrator edits:

  * open a ticket, join an existing one (same device + same issue, or the
    device's open ticket), or only record it;
  * hold "computer offline" alerts briefly, so N computers at one site
    going down together become ONE parent incident ticket instead of a
    ticket storm, and a quick reboot opens nothing;
  * suppress alerts during maintenance windows (and apply the policy when
    the window ends, if the alert is still open);
  * hold non-critical alerts until business hours, or give them to whoever
    is on call;
  * queue, priority (→ SLA due dates), type, technician;
  * escalate when nobody has responded and the alert is still open;
  * on recovery: mark the alert recovered, add a staff note to its ticket,
    and resolve the ticket only when the rule says so AND this alert alone
    opened it AND nobody has worked on it. Never any other ticket.

Mode "legacy" (the default) changes nothing: Rem0te alerts open one ticket
each as before (integrations/rem0te/alerts.py), synced RMM alerts open none.

What this module never does: start a remote session, ask for or authorise an
endpoint action, message a customer, or call an AI model. Everything it
writes is staff-only (tickets are `visibility='staff'`, notes are internal).
Every decision is recorded on an AlertTicketLink with the rule as it stood.

Idempotency: `(connection, external_id)` is unique on AlertTicketLink and the
row is claimed before anything else happens, so a duplicate delivery, a
re-poll or a re-sync finds the row and only updates it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.dispatch import Signal
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    AFTER_HOURS_HOLD, AFTER_HOURS_ON_CALL, ALERT_ATTACH, ALERT_IGNORE, ALERT_MODE_POLICY, ASSIGN_ON_CALL,
    ASSIGN_TECHNICIAN, DISP_ATTACHED, DISP_CREATED, DISP_HELD, DISP_IGNORED, DISP_OUTAGE, DISP_SUPPRESSED,
    DISP_UNMATCHED, MAINT_DROP, RECOVERY_CLOSE_IF_SOLE, AlertIncident, AlertMaintenanceWindow,
    AlertPolicyRule, AlertPolicySettings, AlertTicketLink,
)

logger = logging.getLogger('psa.routing.alerts')

# Sent after an alert's recovery has been handled (link, ticket). Receivers
# (support workflows' outcome verification) must not raise.
alert_recovered = Signal()
# Sent (inside the transaction) when an alert got its ticket after intake —
# released from a hold, joined to an outage. The Rem0te side listens to
# record it on its alert row and link it back (psa/support_workflows/receivers.py);
# routing itself never talks to an RMM.
alert_ticket_opened = Signal()

SEVERITY_PRIORITY = {'critical': 'P1', 'error': 'P2', 'warning': 'P3', 'info': 'P4'}
SEVERITIES = ('info', 'warning', 'error', 'critical')
TICKET_SOURCES = {'rem0te', 'rmm'}

REM0TE_KIND_CATEGORY = {
    'OFFLINE': 'offline', 'DISK_FREE': 'disk', 'CPU_HIGH': 'cpu', 'MEMORY_HIGH': 'memory',
    'SERVICE_STOPPED': 'service', 'REBOOT_PENDING': 'reboot_pending', 'SITE_OUTAGE': 'site_outage',
}
# First match wins; checked against the alert type and text, lower-cased.
KEYWORDS = [
    ('backup', [r'\bbackup']),
    ('security', [r'antivirus', r'defender', r'malware', r'threat', r'\bedr\b', r'ransomware', r'virus',
                  r'tamper', r'quarantin', r'firewall (is )?(disabled|off)']),
    ('reboot_pending', [r'reboot (is )?(pending|required)', r'pending reboot', r'restart (is )?(pending|required)',
                        r'pending restart']),
    ('windows_update', [r'windows update', r'update(s)? fail', r'patch(es|ing)? fail', r'\bkb\d{4,}',
                        r'wuauserv', r'failed to install update']),
    ('offline', [r'offline', r'agent not responding', r'not checking in', r'overdue', r'heartbeat',
                 r'unreachable', r'not responding to ping', r'\bis down\b']),
    ('disk', [r'\bdisk', r'\bdrive\b', r'free space', r'low space', r'storage', r'\bvolume']),
    ('cpu', [r'\bcpu', r'processor']),
    ('memory', [r'memory', r'\bram\b']),
    ('unresponsive_app', [r'not responding', r'\bhung\b', r'unresponsive', r'\bfrozen\b', r'\bhang']),
    ('service', [r'\bservice']),
    ('application', [r'application', r'\bcrash', r'faulting', r'exception', r'app error', r'event id \d+']),
    ('network', [r'network', r'packet loss', r'latency', r'\bdns\b', r'gateway', r'link (is )?down', r'\bping\b']),
]
_SERVICE_RE = re.compile(r"service\s+['\"]?([A-Za-z0-9_.\-]{1,64})", re.I)


class NotReady(Exception):
    """PSA is not set up enough to open a ticket (no queue or status)."""


def _text(value, limit) -> str:
    if value is None:
        return ''
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(value))
    return s.strip()[:limit]


def classify(kind: str = '', *texts: str) -> str:
    """Category for an alert. Rem0te kinds map directly; anything else (or
    Rem0te's EVENT_MATCH) is classified by keywords."""
    mapped = REM0TE_KIND_CATEGORY.get((kind or '').upper())
    if mapped:
        return mapped
    hay = ' '.join(t for t in ((kind or ''),) + texts if t).lower()
    for category, patterns in KEYWORDS:
        if any(re.search(p, hay) for p in patterns):
            return category
    return 'other'


def service_name(title: str) -> str:
    m = _SERVICE_RE.search(title or '')
    return m.group(1).lower() if m else ''


def mode_active(source: str) -> bool:
    s = AlertPolicySettings.load()
    if s.mode != ALERT_MODE_POLICY:
        return False
    return source == AlertTicketLink.SOURCE_REM0TE or s.include_rmm_sync


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

@dataclass
class AlertFacts:
    source: str
    connection: object
    external_id: str
    organization: object = None
    device: object = None
    asset: object = None
    endpoint_id: str = ''
    device_name: str = ''
    device_type: str = ''
    site_name: str = ''
    site_key: str = ''
    category: str = 'other'
    severity: str = 'warning'
    state: str = 'open'
    title: str = ''
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    occurrences: int = 1
    sequence: int = 0
    outage_parent: str = ''
    unmatched_reason: str = ''
    evidence: dict = field(default_factory=dict)

    @property
    def issue_key(self) -> str:
        if self.device is not None:
            dev = f'dev:{self.device.pk}'
        elif self.endpoint_id:
            dev = f'ep:{self.connection.pk}:{self.endpoint_id}'
        elif self.device_name:
            dev = f'name:{self.connection.pk}:{self.device_name.lower()}'
        else:
            dev = f'alert:{self.connection.pk}:{self.external_id}'
        extra = service_name(self.title) if self.category == 'service' else ''
        return f'{dev}|{self.category}' + (f'|{extra}' if extra else '')


def _site_key(connection, device, site_name) -> str:
    if device is not None and getattr(device, 'site_id', ''):
        return f'{connection.pk}:id:{device.site_id}'[:300]
    name = (site_name or '').strip().lower()
    return f'name:{name}'[:300] if name else ''


def _dt(value):
    if isinstance(value, datetime):
        return value
    try:
        return parse_datetime(str(value or '').replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _device_asset(device):
    if device is None:
        return None
    asset = getattr(device, 'linked_asset', None)
    if asset is None or asset.organization_id != device.organization_id:
        return None
    if device.link_status in (device.LINK_REVIEW, device.LINK_UNLINKED):
        return None
    return asset


PATCH_KEYS = ('evidence_source', 'evidence_at', 'evidence_age_hours', 'freshness', 'last_boot_at', 'managed_by',
              'reboot_required', 'pending_count', 'pending_kbs', 'confirmed_kbs', 'failed_kbs',
              'awaiting_confirmation_kbs', 'deploy_available')


def _patch_summary(raw):
    if not isinstance(raw, dict):
        return None
    out = {}
    for k in PATCH_KEYS:
        v = raw.get(k)
        if isinstance(v, list):
            out[k] = [_text(x, 20) for x in v[:20]]
        elif isinstance(v, (bool, int, float)) or v is None:
            out[k] = v
        else:
            out[k] = _text(v, 40)
    return out


def from_rem0te(connection, alert: dict, sequence: int = 0, device=None) -> AlertFacts:
    """A Rem0te alert (contract ticket-rmm-v1). The customer is the
    connection's own; `device` is the one the Rem0te intake matched by
    Rem0te's computer id (never by name), and is dropped unless it is this
    connection's, this customer's and not under review."""
    org = connection.organization
    endpoint = _text(alert.get('rem0te_endpoint_id'), 64)
    if device is not None and (device.connection_id != connection.pk
                               or device.organization_id != connection.organization_id
                               or device.external_id != endpoint
                               or device.link_status in (device.LINK_REVIEW, device.LINK_UNLINKED)):
        device = None
    title = _text(alert.get('title'), 300)
    site = _text(alert.get('site_name'), 128) or (device.site_name if device else '')
    state = alert.get('state') if alert.get('state') in ('open', 'acknowledged', 'resolved') else 'open'
    severity = alert.get('severity') if alert.get('severity') in SEVERITIES else 'warning'
    evidence = {
        'kind': _text(alert.get('kind'), 20), 'monitor': _text(alert.get('monitor'), 64), 'title': title,
        'severity': severity, 'state': state, 'occurrences': alert.get('occurrences'),
        'first_seen_at': _text(alert.get('first_seen_at'), 40), 'last_seen_at': _text(alert.get('last_seen_at'), 40),
        'computer_name': _text(alert.get('computer_name'), 128), 'site_name': site,
    }
    patch = _patch_summary(alert.get('patch_summary'))
    if patch is not None:
        evidence['patch_summary'] = patch
    return AlertFacts(
        source=AlertTicketLink.SOURCE_REM0TE, connection=connection, external_id=_text(alert.get('alert_id'), 64),
        organization=org, device=device, asset=_device_asset(device), endpoint_id=endpoint,
        device_name=(device.device_name if device else _text(alert.get('computer_name'), 128)),
        device_type=(device.device_type if device else ''), site_name=site,
        site_key=_site_key(connection, device, site),
        category=classify(alert.get('kind') or '', title), severity=severity, state=state, title=title,
        first_seen_at=_dt(alert.get('first_seen_at')), last_seen_at=_dt(alert.get('last_seen_at')),
        occurrences=max(1, int(alert.get('occurrences') or 1)), sequence=int(sequence or 0),
        outage_parent=_text(alert.get('outage_alert_id'), 64), evidence=evidence)


def from_rmm_alert(alert) -> AlertFacts:
    """An alert synced from another RMM provider (integrations.RMMAlert). Its
    customer is its device's, and only once that is settled."""
    device = alert.device
    org = alert.organization if (device is not None and device.is_exposed
                                 and device.organization_id == alert.organization_id) else None
    message = _text(alert.message, 500)
    title = _text(f'{device.device_name}: {message or alert.alert_type}' if device else message, 300)
    status = (alert.status or '').lower()
    state = 'resolved' if status in ('resolved', 'closed') else ('acknowledged' if status == 'acknowledged' else 'open')
    severity = alert.severity if alert.severity in SEVERITIES else 'warning'
    site = device.site_name if device else ''
    return AlertFacts(
        source=AlertTicketLink.SOURCE_RMM, connection=alert.connection, external_id=_text(alert.external_id, 255),
        organization=org, device=device if org is not None else None,
        asset=_device_asset(device) if org is not None else None,
        endpoint_id=_text(device.external_id if device else '', 255),
        device_name=device.device_name if device else '', device_type=device.device_type if device else '',
        site_name=site, site_key=_site_key(alert.connection, device, site),
        category=classify('', alert.alert_type or '', message), severity=severity, state=state, title=title,
        first_seen_at=alert.triggered_at, last_seen_at=alert.resolved_at or alert.triggered_at,
        unmatched_reason='' if org is not None else "The device's customer is not settled.",
        evidence={'alert_type': _text(alert.alert_type, 255), 'message': message, 'severity': severity,
                  'status': status, 'triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else ''})


def from_link(link) -> AlertFacts:
    """Rebuild the facts from a stored link (releasing a hold)."""
    device = link.device
    if device is not None and (device.organization_id != link.organization_id):
        device = None
    return AlertFacts(
        source=link.source, connection=link.connection, external_id=link.external_id,
        organization=link.organization, device=device, asset=_device_asset(device),
        endpoint_id=link.endpoint_id, device_name=link.device_name,
        device_type=device.device_type if device else '', site_name=link.site_name, site_key=link.site_key,
        category=link.category, severity=link.severity, state=link.state, title=link.title,
        first_seen_at=link.first_seen_at, last_seen_at=link.last_seen_at, occurrences=link.occurrences,
        sequence=link.last_sequence, evidence=link.evidence or {})


# ---------------------------------------------------------------------------
# Rules (read only)
# ---------------------------------------------------------------------------

def _as_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def rule_failures(conditions, f: AlertFacts) -> List[str]:
    """Empty = matches. Otherwise why not, in plain words."""
    c = conditions or {}
    out = []
    for key, value, label in (('sources', f.source, 'source'), ('categories', f.category, 'category'),
                              ('severities', f.severity, 'severity'), ('device_types', f.device_type, 'device type')):
        wanted = _as_list(c.get(key))
        if wanted and value not in wanted:
            out.append(f'{label} is "{value or "none"}", not one of {", ".join(wanted)}')
    sites = [s.lower() for s in _as_list(c.get('sites'))]
    if sites and (f.site_name or '').strip().lower() not in sites:
        out.append(f'site is "{f.site_name or "none"}", not one of {", ".join(sites)}')
    return out


def matching_rule(f: AlertFacts) -> Optional[AlertPolicyRule]:
    org_id = getattr(f.organization, 'pk', None)
    rules = list(AlertPolicyRule.objects.filter(is_active=True)
                 .filter(Q(organization__isnull=True) | Q(organization_id=org_id))
                 .select_related('queue', 'ticket_priority', 'ticket_type', 'assign_user'))
    rules.sort(key=lambda r: (0 if r.organization_id else 1, r.priority, r.pk))
    for r in rules:
        if not rule_failures(r.conditions, f):
            return r
    return None


def maintenance_for(f: AlertFacts, now) -> Optional[AlertMaintenanceWindow]:
    if f.organization is None:
        return None
    qs = (AlertMaintenanceWindow.objects.filter(organization=f.organization, is_cancelled=False,
                                                starts_at__lte=now, ends_at__gt=now)
          .order_by('-ends_at'))
    for w in qs:
        if w.device_id and (f.device is None or w.device_id != f.device.pk):
            continue
        if w.site_name and w.site_name.strip().lower() != (f.site_name or '').strip().lower():
            continue
        cats = _as_list(w.categories)
        if cats and f.category not in cats:
            continue
        return w
    return None


def in_business_hours(now, organization) -> bool:
    from . import engine
    from .models import RoutingSettings
    return engine.in_business_hours(now, RoutingSettings.load(), organization)


def _authorized(user, organization) -> str:
    """'' when `user` may be given this customer's tickets, else why not."""
    from . import engine
    cust = engine.customer_settings(organization)
    ids = set()
    if cust is not None and cust.restrict_technicians:
        ids = set(cust.authorized_technicians.values_list('pk', flat=True))
    return engine._authorization_problem(user, organization, cust, ids) or ''


def _assignee(f: AlertFacts, rule, now):
    """(user or None, explanation)."""
    if rule is None:
        return None, ''
    mode = rule.assign_mode
    if rule.after_hours == AFTER_HOURS_ON_CALL and not in_business_hours(now, f.organization):
        mode = ASSIGN_ON_CALL
    if mode == ASSIGN_TECHNICIAN and rule.assign_user_id:
        problem = _authorized(rule.assign_user, f.organization)
        if problem:
            return None, f'Not assigned to {rule.assign_user.get_username()}: {problem}.'
        return rule.assign_user, f'Assigned to {rule.assign_user.get_username()} by the alert rule.'
    if mode == ASSIGN_ON_CALL:
        from .models import OnCallShift
        for shift in (OnCallShift.objects.filter(starts_at__lte=now, ends_at__gt=now)
                      .select_related('user').order_by('starts_at', 'pk')):
            if not _authorized(shift.user, f.organization):
                return shift.user, f'Assigned to {shift.user.get_username()} (on call now).'
        return None, 'Nobody authorized for this customer is on call; left for the queue.'
    return None, ''


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def note(ticket, body, author=None):
    """A staff-only note on the ticket. Never shown to the customer."""
    from psa.models import TicketComment
    return TicketComment.objects.create(ticket=ticket, author=author, body=body[:8000], is_internal=True,
                                        is_system=author is None, source='monitoring')


def _queue_for(rule, s):
    from psa.models import Queue
    for q in ((rule.queue if rule else None), s.default_queue):
        if q is not None and q.is_active:
            return q
    return (Queue.objects.filter(name='Monitoring', is_active=True).first()
            or Queue.objects.filter(is_active=True).order_by('sort_order', 'pk').first())


def _priority_for(rule, severity):
    from psa.models import TicketPriority
    if rule is not None and rule.ticket_priority_id:
        return rule.ticket_priority
    return (TicketPriority.objects.filter(code=SEVERITY_PRIORITY.get(severity, 'P3')).first()
            or TicketPriority.objects.order_by('sort_order').first())


def _type_for(rule):
    from psa.models import TicketType
    if rule is not None and rule.ticket_type_id:
        return rule.ticket_type
    return (TicketType.objects.filter(slug='monitoring-alert').first()
            or TicketType.objects.filter(is_active=True).order_by('sort_order').first())


def _describe(f: AlertFacts, why_lines=()):
    lines = [
        'Opened by the alert policy for a monitoring alert.', '',
        f'Alert: {f.title or "—"}',
        f'Category: {f.category}   Severity: {f.severity}   State: {f.state}',
        f'Computer (as reported by the device): {f.device_name or "—"}',
        f'Site: {f.site_name or "—"}',
        f'First seen: {f.first_seen_at.isoformat() if f.first_seen_at else "—"}   Occurrences: {f.occurrences}',
        f'Source: {f.source} ({f.connection.name})   Alert id: {f.external_id}',
    ]
    lines += [w for w in why_lines if w]
    lines += ['', 'Nothing in ClientSt0r acts on the computer. Diagnostics and fixes go through the '
                  'RMM, with its approval.']
    return '\n'.join(lines)


def _create_ticket(f: AlertFacts, link, rule, s, now, *, subject=None, description=None, severity=None,
                   asset='same', category=None):
    from psa.models import Ticket, TicketStatus
    from psa.sla import apply_due_dates
    queue = _queue_for(rule, s)
    status = TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.order_by('sort_order').first()
    priority = _priority_for(rule, severity or f.severity)
    ttype = _type_for(rule)
    if queue is None or status is None or priority is None or ttype is None:
        raise NotReady('PSA has no ticket queue, status, priority or type yet (run psa_seed_defaults).')
    assignee, assign_why = _assignee(f, rule, now)
    cat = category or f.category
    ticket = Ticket(
        organization=f.organization, subject=(subject or f'[Alert] {f.title or cat}')[:300],
        description=description or _describe(f, [assign_why]), queue=queue, priority=priority, status=status,
        ticket_type=ttype, source='rmm', visibility='staff', client_can_view=False,
        related_asset=f.asset if asset == 'same' else asset, assigned_to=assignee,
        tags=['alert', f'alert:{cat}'],
        custom_fields={'alert_policy': {'link_id': link.pk, 'issue_key': link.issue_key, 'category': cat,
                                        'rule_id': rule.pk if rule else None}})
    ticket.save()
    apply_due_dates(ticket)
    return ticket, assign_why


def _set(link, disposition, reason, **fields):
    link.disposition = disposition
    link.reason = (reason or '')[:4000]
    for k, v in fields.items():
        setattr(link, k, v)


def _claim(f: AlertFacts, now):
    """(link, created). The insert happens first; a concurrent or repeated
    delivery gets the existing row (locked where the database can)."""
    try:
        with transaction.atomic():
            link = AlertTicketLink.objects.create(
                source=f.source, connection=f.connection, external_id=f.external_id[:255],
                organization=f.organization, device=f.device, endpoint_id=f.endpoint_id[:255],
                device_name=f.device_name[:255], site_key=f.site_key[:300], site_name=f.site_name[:255],
                category=f.category, severity=f.severity, state=f.state, title=f.title[:300],
                issue_key=f.issue_key[:300], disposition=DISP_HELD, hold_reason='intake',
                evidence=f.evidence, first_seen_at=f.first_seen_at or now, last_seen_at=f.last_seen_at or now,
                occurrences=f.occurrences, last_sequence=f.sequence)
        return link, True
    except IntegrityError:
        link = (AlertTicketLink.objects.select_for_update()
                .get(connection=f.connection, external_id=f.external_id[:255]))
        return link, False


def process(f: AlertFacts, now=None):
    """Apply the policy to one alert. Returns the AlertTicketLink. Safe to
    call any number of times for the same alert."""
    now = now or timezone.now()
    s = AlertPolicySettings.load()
    with transaction.atomic():
        link, created = _claim(f, now)
        if created:
            _place(link, f, now, s)
            link.save()
        else:
            _update(link, f, now, s)
    return link


def _place(link, f: AlertFacts, now, s, releasing=False):
    """Decide what happens to a new (or released) alert. Caller saves `link`."""
    if f.organization is None:
        return _set(link, DISP_UNMATCHED, f.unmatched_reason or 'No customer for this alert; nothing opened.',
                    hold_reason='', hold_until=None)
    if f.state == 'resolved':
        return _set(link, DISP_IGNORED, 'Already recovered when it arrived; nothing opened.', hold_reason='',
                    hold_until=None, recovered_at=link.recovered_at or now, recovery_handled=True)
    window = maintenance_for(f, now)
    if window is not None:
        return _set(link, DISP_SUPPRESSED, f'Suppressed by maintenance until {window.ends_at:%Y-%m-%d %H:%M}'
                                           f'{": " + window.reason if window.reason else ""}.',
                    hold_reason='maintenance', hold_until=window.ends_at, maintenance=window)
    rule = matching_rule(f)
    link.rule = rule
    link.rule_snapshot = rule.snapshot() if rule else {}
    action = rule.action if rule else s.default_action
    why_rule = f'Rule "{rule.name}"' if rule else 'No alert rule matched; default policy'
    if action == ALERT_IGNORE:
        return _set(link, DISP_IGNORED, f'{why_rule}: record only.', hold_reason='', hold_until=None)

    # The RMM grouped this alert under its own site-outage alert.
    if f.outage_parent:
        inc = (AlertIncident.objects.filter(organization=f.organization, status='open',
                                            source_alert_key=_outage_key(f.connection, f.outage_parent)).first())
        if inc is not None and inc.ticket_id:
            return _join_incident(link, inc, f'{why_rule}: part of the RMM\'s site outage.')
    if f.category == 'site_outage':
        return _open_incident(link, f, rule, s, now, why_rule, source_key=_outage_key(f.connection, f.external_id))

    # Same device, same issue, ticket still open: join it.
    existing = _open_issue_link(link)
    if existing is not None:
        _set(link, DISP_ATTACHED, f'{why_rule}: repeat of {existing.external_id} on the same device; joined '
                                  f'{existing.ticket.ticket_number}.', ticket=existing.ticket, hold_reason='',
             hold_until=None)
        note(existing.ticket, f'Repeat alert on the same device and issue: {f.title}. Recorded here instead of '
                              'opening another ticket.')
        return None

    if f.category == 'offline':
        if f.site_key and s.site_outage_threshold:
            inc = (AlertIncident.objects.filter(organization=f.organization, site_key=f.site_key, status='open')
                   .exclude(ticket__isnull=True).first())
            if inc is not None:
                return _join_incident(link, inc, f'{why_rule}: the site already has an open outage.')
            peers = _offline_peers(link, now, s)
            computers = {p.device_id or p.issue_key for p in peers} | {link.device_id or link.issue_key}
            if len(computers) >= s.site_outage_threshold:
                return _open_incident(link, f, rule, s, now, why_rule, peers=peers)
        if not releasing and s.offline_hold_minutes:
            return _set(link, DISP_HELD, f'Held {s.offline_hold_minutes} min: a computer offline is often a '
                                         'reboot, or part of a site outage.', hold_reason='offline',
                        hold_until=now + timedelta(minutes=s.offline_hold_minutes))

    if (rule is not None and rule.after_hours == AFTER_HOURS_HOLD and f.severity != 'critical'
            and not in_business_hours(now, f.organization)):
        return _set(link, DISP_HELD, f'{why_rule}: held until business hours.', hold_reason='after_hours',
                    hold_until=None)

    if action == ALERT_ATTACH and f.asset is not None:
        from psa.models import Ticket
        t = (Ticket.objects.filter(organization=f.organization, related_asset=f.asset)
             .exclude(status__is_terminal=True).order_by('-created_at').first())
        if t is not None:
            _set(link, DISP_ATTACHED, f'{why_rule}: joined the device\'s open ticket {t.ticket_number}.',
                 ticket=t, hold_reason='', hold_until=None)
            note(t, f'Monitoring alert on this device: {f.title} ({f.severity}). Joined this ticket by the '
                    'alert policy.')
            return None

    ticket, assign_why = _create_ticket(f, link, rule, s, now)
    return _set(link, DISP_CREATED, f'{why_rule}: opened {ticket.ticket_number}. {assign_why}'.strip(),
                ticket=ticket, hold_reason='', hold_until=None)


def _outage_key(connection, alert_id):
    return f'{connection.pk}:{alert_id}'[:300]


def _open_issue_link(link):
    return (AlertTicketLink.objects.filter(organization_id=link.organization_id, issue_key=link.issue_key,
                                           ticket__isnull=False, disposition__in=[DISP_CREATED, DISP_ATTACHED])
            .exclude(pk=link.pk).exclude(ticket__status__is_terminal=True)
            .select_related('ticket').order_by('-created_at').first())


def _offline_peers(link, now, s):
    since = now - timedelta(minutes=max(1, s.site_outage_window_minutes))
    return list(AlertTicketLink.objects.filter(
        organization_id=link.organization_id, site_key=link.site_key, category='offline',
        disposition__in=[DISP_HELD, DISP_CREATED], incident__isnull=True, created_at__gte=since)
        .exclude(state='resolved').exclude(pk=link.pk).select_for_update())


def _join_incident(link, inc, reason):
    _set(link, DISP_OUTAGE, f'{reason} Recorded on {inc.ticket.ticket_number}.', ticket=inc.ticket, incident=inc,
         hold_reason='', hold_until=None)
    AlertIncident.objects.filter(pk=inc.pk).update(member_count=F('member_count') + 1)
    _ticket_opened_later(link)
    return None


def _open_incident(link, f: AlertFacts, rule, s, now, why_rule, peers=(), source_key=''):
    inc = AlertIncident.objects.create(organization=f.organization, site_key=f.site_key or f'alert:{f.external_id}',
                                       site_name=f.site_name, source_alert_key=source_key, opened_at=now)
    names = sorted({p.device_name or p.external_id for p in peers} | ({f.device_name} if f.device_name else set()))
    n = len(peers) + (0 if source_key else 1)
    site = f.site_name or 'an unnamed site'
    subject = (f'[Alert] Site outage: {site}' + (f' — {n} computers offline' if n > 1 else ''))[:300]
    desc = _describe(f, [
        '', f'Site outage: {n} computer(s) offline at {site} within {s.site_outage_window_minutes} minutes.'
        if not source_key else 'The RMM reported a site outage.',
        'One ticket for the site: the computers\' own alerts are recorded here instead of each opening a ticket.',
    ])
    ticket, _why = _create_ticket(f, link, rule, s, now, subject=subject, description=desc, severity='critical',
                                  asset=None, category='site_outage')
    inc.ticket = ticket
    inc.member_count = n
    inc.save(update_fields=['ticket', 'member_count'])
    for p in peers:
        p.incident = inc
        if p.ticket_id and p.disposition == DISP_CREATED:
            # Opened before the outage was recognised: keep it, as a child.
            from psa.models import Ticket
            Ticket.objects.filter(pk=p.ticket_id, parent_ticket__isnull=True).update(parent_ticket=ticket)
            p.reason = (p.reason + f' Linked as a child of site outage {ticket.ticket_number}.')[:4000]
        else:
            p.disposition, p.ticket, p.hold_reason, p.hold_until = DISP_OUTAGE, ticket, '', None
            p.reason = (p.reason + f' Part of site outage {ticket.ticket_number}.')[:4000]
            _ticket_opened_later(p)
        p.save()
    listed = ', '.join(names[:50]) + (f' and {len(names) - 50} more' if len(names) > 50 else '')
    if names:
        note(ticket, f'Computers in this outage so far: {listed}.')
    disp = DISP_CREATED if source_key else DISP_OUTAGE
    return _set(link, disp, f'{why_rule}: site outage, opened {ticket.ticket_number}.', ticket=ticket,
                incident=inc, hold_reason='', hold_until=None)


def _ticket_opened_later(link):
    """An alert that got its ticket after intake: tell the intake side
    (alert_ticket_opened) so it can record and link it back."""
    if link.ticket is None:
        return
    try:
        alert_ticket_opened.send(sender=AlertTicketLink, link=link, ticket=link.ticket)
    except Exception:  # noqa: BLE001 — retried by the intake's own poller
        logger.exception('alert_ticket_opened receivers failed for link %s', link.pk)


# ---------------------------------------------------------------------------
# Updates and recovery
# ---------------------------------------------------------------------------

def _update(link, f: AlertFacts, now, s):
    if f.sequence and link.last_sequence and f.sequence <= link.last_sequence:
        return link  # an older event, delivered late
    was_resolved = link.state == 'resolved'
    link.severity, link.state = f.severity, f.state
    link.title = f.title[:300] or link.title
    link.last_seen_at = f.last_seen_at or now
    link.occurrences = max(link.occurrences, f.occurrences)
    link.last_sequence = max(link.last_sequence, f.sequence)
    if f.evidence:
        link.evidence = f.evidence
    if f.state == 'resolved' and not was_resolved:
        link.recovered_at = now
        link.save()
        _recover(link, now, s)
        return link
    if was_resolved and f.state != 'resolved':
        link.recovered_at, link.recovery_handled = None, False
        if link.ticket_id and not link.ticket.status.is_terminal:
            note(link.ticket, f'Monitoring reports the alert is active again: {link.title}.')
    link.save()
    return link


def recover(link, now=None):
    """Public entry for a recovery noticed elsewhere (e.g. the alert row)."""
    now = now or timezone.now()
    with transaction.atomic():
        link = AlertTicketLink.objects.select_for_update().get(pk=link.pk)
        if link.state != 'resolved':
            link.state, link.recovered_at = 'resolved', now
            link.save(update_fields=['state', 'recovered_at', 'updated_at'])
        _recover(link, now, AlertPolicySettings.load())
    return link


def _recover(link, now, s):
    if link.recovery_handled:
        return
    link.recovery_handled = True
    if link.disposition in (DISP_HELD, DISP_SUPPRESSED):
        link.reason = (link.reason + ' Recovered before a ticket was opened; nothing opened.')[:4000]
        link.hold_until, link.hold_reason = None, ''
        link.save()
        return
    link.save()
    if link.incident_id:
        _maybe_close_incident(link.incident, now)
    ticket = link.ticket
    if ticket is None or link.disposition == DISP_OUTAGE:
        _signal(link, ticket)
        return
    closed, why = False, ''
    if (link.rule_snapshot or {}).get('on_recovery') == RECOVERY_CLOSE_IF_SOLE:
        ok, why = sole_alert_ticket(link, ticket)
        if ok:
            closed = _resolve_ticket(ticket, link, now)
            if not closed:
                why = 'the ticket could not be resolved automatically (a sign-off or checklist is required)'
    if s.post_recovery_notes or closed or why:
        when = timezone.localtime(now).strftime('%Y-%m-%d %H:%M')
        tail = ('Resolved this ticket: the alert alone opened it and nobody had worked on it.' if closed
                else (f'Ticket left open: {why}.' if why else 'The ticket stays open for a person to close.'))
        if not ticket.status.is_terminal or closed:
            note(ticket, f'Monitoring reports the alert recovered at {when}: {link.title}. {tail}')
    _signal(link, ticket)


def _signal(link, ticket):
    try:
        alert_recovered.send(sender=AlertTicketLink, link=link, ticket=ticket)
    except Exception:  # noqa: BLE001
        logger.exception('alert_recovered receivers failed for link %s', link.pk)


def sole_alert_ticket(link, ticket):
    """(True, '') only when this alert alone opened `ticket` and nobody has
    worked on it. Anything else is a reason the ticket must stay open."""
    from psa.models import TicketComment
    if ticket.status.is_terminal:
        return False, 'it is already closed'
    marker = (ticket.custom_fields or {}).get('alert_policy') or {}
    if link.disposition != DISP_CREATED or marker.get('link_id') != link.pk:
        return False, 'this alert did not open it'
    if AlertTicketLink.objects.filter(ticket=ticket).exclude(pk=link.pk).exists():
        return False, 'other alerts are recorded on it'
    if ticket.child_tickets.exists() or getattr(ticket, 'parent_ticket_id', None):
        return False, 'it is part of a parent/child group'
    if TicketComment.objects.filter(ticket=ticket).filter(Q(is_system=False) | Q(author__isnull=False)).exists():
        return False, 'people have worked on it'
    if ticket.first_response_at or ticket.time_entries.exists():
        return False, 'people have worked on it'
    return True, ''


def _resolve_ticket(ticket, link, now) -> bool:
    from django.core.exceptions import ValidationError
    from psa.models import TicketStatus
    status = (TicketStatus.objects.filter(slug='resolved', is_terminal=True).first()
              or TicketStatus.objects.filter(is_terminal=True).order_by('sort_order').first())
    if status is None or getattr(status, 'requires_signoff', False):
        return False
    ticket.status = status
    ticket.resolved_at = now
    ticket.closure_category = 'no_action'
    ticket.resolution_summary = f'Monitoring alert recovered on its own ({link.title}).'[:2000]
    ticket.updated_by = None
    try:
        with transaction.atomic():
            ticket.save(update_fields=['status', 'resolved_at', 'closure_category', 'resolution_summary',
                                       'updated_by', 'updated_at'])
    except ValidationError:
        return False
    return True


def _maybe_close_incident(inc, now):
    if inc.status != 'open':
        return
    if AlertTicketLink.objects.filter(incident=inc).exclude(state='resolved').exists():
        return
    AlertIncident.objects.filter(pk=inc.pk, status='open').update(status='resolved', resolved_at=now)
    if inc.ticket_id and not inc.ticket.status.is_terminal:
        note(inc.ticket, f'Monitoring reports every computer in this site outage is back '
                         f'({inc.members.count()} alert(s)). The ticket stays open for a person to close.')


# ---------------------------------------------------------------------------
# Periodic work (psa_sla_workflow_tick)
# ---------------------------------------------------------------------------

def _release(link_id, now, s):
    with transaction.atomic():
        link = (AlertTicketLink.objects.select_for_update().select_related('connection', 'organization', 'device')
                .get(pk=link_id))
        if link.disposition not in (DISP_HELD, DISP_SUPPRESSED) or link.state == 'resolved':
            return None
        if link.disposition == DISP_SUPPRESSED and link.maintenance_id and link.maintenance.after_window == MAINT_DROP:
            _set(link, DISP_IGNORED, link.reason + ' The maintenance window said not to open a ticket.',
                 hold_until=None, hold_reason='')
            link.save()
            return link
        _place(link, from_link(link), now, s, releasing=True)
        link.save()
        if link.ticket_id and link.disposition in (DISP_CREATED, DISP_ATTACHED):
            _ticket_opened_later(link)
    return link


def _escalate(link_id, now):
    from psa.models import TicketPriority, Queue
    from psa.sla import apply_due_dates
    from .service import _Applying
    with transaction.atomic():
        link = AlertTicketLink.objects.select_for_update().select_related('ticket', 'ticket__status').get(pk=link_id)
        snap = link.rule_snapshot or {}
        minutes = snap.get('escalate_after_minutes')
        t = link.ticket
        if (link.escalated_at or not minutes or t is None or link.state == 'resolved'
                or t.status.is_terminal or now - link.created_at < timedelta(minutes=int(minutes))):
            return None
        link.escalated_at = now
        link.save(update_fields=['escalated_at', 'updated_at'])
        if t.first_response_at or t.escalated_at:
            return None  # someone responded, or it is already escalated
        fields = ['escalated_at', 'escalation_reason', 'updated_at']
        t.escalated_at = now
        t.escalation_reason = f'Alert still open after {minutes} minutes with no response.'[:500]
        prio = TicketPriority.objects.filter(pk=snap.get('escalation_priority_id') or 0).first()
        if prio is not None and prio.pk != t.priority_id:
            t.priority = prio
            fields.append('priority')
        queue = Queue.objects.filter(pk=snap.get('escalation_queue_id') or 0, is_active=True).first()
        if queue is not None and queue.pk != t.queue_id:
            t.queue = queue
            fields.append('queue')
        t.updated_by = None
        with _Applying():
            t.save(update_fields=fields)
        if 'priority' in fields:
            apply_due_dates(t)
        changes = ', '.join(x for x in (f'priority {prio.code}' if 'priority' in fields else '',
                                        f'queue {queue.name}' if 'queue' in fields else '') if x)
        note(t, f'Escalated by the alert policy: the alert is still open after {minutes} minutes and nobody '
                f'has responded.' + (f' Changed {changes}.' if changes else ''))
        return link


def tick(now=None, limit=500) -> dict:
    """Release held alerts that are due, apply the policy to alerts whose
    maintenance window ended, and escalate. No-op in legacy mode."""
    now = now or timezone.now()
    s = AlertPolicySettings.load()
    stats = {'released': 0, 'escalated': 0}
    if s.mode != ALERT_MODE_POLICY:
        return stats
    due = list(AlertTicketLink.objects.filter(
        Q(disposition=DISP_HELD, hold_reason='offline', hold_until__lte=now)
        | Q(disposition=DISP_SUPPRESSED, hold_until__lte=now))
        .exclude(state='resolved').order_by('created_at').values_list('pk', flat=True)[:limit])
    for link in (AlertTicketLink.objects.filter(disposition=DISP_HELD, hold_reason='after_hours')
                 .exclude(state='resolved').select_related('organization').order_by('created_at')[:limit]):
        if in_business_hours(now, link.organization):
            due.append(link.pk)
    for pk in due:
        try:
            if _release(pk, now, s) is not None:
                stats['released'] += 1
        except NotReady:
            break
        except Exception:  # noqa: BLE001
            logger.exception('releasing held alert %s failed', pk)
    for pk in (AlertTicketLink.objects.filter(disposition=DISP_CREATED, escalated_at__isnull=True,
                                              ticket__isnull=False, rule__escalate_after_minutes__isnull=False)
               .exclude(state='resolved').values_list('pk', flat=True)[:limit]):
        try:
            if _escalate(pk, now) is not None:
                stats['escalated'] += 1
        except Exception:  # noqa: BLE001
            logger.exception('escalating alert %s failed', pk)
    return stats


# ---------------------------------------------------------------------------
# Entry points for the intake paths
# ---------------------------------------------------------------------------

def rem0te_event(connection, event: dict, device=None):
    """Called by integrations/rem0te/alerts.py inside its dedup transaction
    when the policy is on, with the device it matched. Returns the ticket for
    the alert (or None: held, suppressed, ignored)."""
    f = from_rem0te(connection, event['alert'], event.get('sequence') or 0, device=device)
    if not f.external_id:
        return None
    link = process(f)
    return link.ticket if link.disposition in (DISP_CREATED, DISP_ATTACHED, DISP_OUTAGE) else None


def rmm_alert_synced(alert):
    """Called after an RMM sync stored an alert. No-op unless the policy is
    on and covers synced alerts. Never raises into the sync."""
    try:
        if not mode_active(AlertTicketLink.SOURCE_RMM):
            return None
        f = from_rmm_alert(alert)
        if not f.external_id:
            return None
        if f.state == 'resolved' and not AlertTicketLink.objects.filter(
                connection=f.connection, external_id=f.external_id).exists():
            return None  # a recovered alert we never saw open: nothing to do
        return process(f)
    except Exception:  # noqa: BLE001 — the sync must carry on
        logger.exception('alert policy failed for RMM alert %s', getattr(alert, 'pk', None))
        return None


def links_for_ticket(ticket):
    return list(AlertTicketLink.objects.filter(Q(ticket=ticket) | Q(incident__ticket=ticket))
                .select_related('connection', 'device', 'incident').distinct().order_by('-created_at')[:50])
