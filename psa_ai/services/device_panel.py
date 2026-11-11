"""
The ticket's RMM side panel, per affected device (ClientSt0r ↔ RMM Phase 4).

rmm_actions.panel() decides what each device can do; this adds what the
technician needs around it, from stored data only:

  * every device the ticket is about (psa.affected.ticket_assets), with or
    without an RMM, and its health (online / offline / stale / unknown);
  * recent alerts and recent relevant changes (software installed in the
    last 14 days, Rem0te alert activity);
  * this ticket's requests and remote launches for that device, with their
    results. A launch is only ever "link issued — session not confirmed":
    no RMM tells ClientSt0r that a session started, so nothing here says so.

Plus two technician steps with server-side rules:

  attach_note(...)       a request's outcome as an internal (staff-only) note,
                         only when the technician asks for it
  verification(ticket)   is there evidence the problem is gone, per device?
                         Close-after-verify (rmm_views.verify_close) re-runs it
                         on POST; closing with checks failing or unknown needs
                         an explicit acknowledgement, and the closeout rules of
                         the Close button still apply.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

from django.utils import timezone

RECENT_ALERT_DAYS = 7
RECENT_CHANGE_DAYS = 14
NOTE_RESULT_CHARS = 1500


def launches_for_ticket(ticket, devices) -> List[dict]:
    """Remote launches handed out from this ticket (audit log), newest first."""
    from audit.models import AuditLog
    pks = {d.pk for d in devices}
    out = []
    rows = (AuditLog.objects.filter(object_type='psa_ai.RemoteLaunch', organization_id=ticket.organization_id,
                                    object_repr__endswith=ticket.ticket_number)
            .select_related('user').order_by('-timestamp')[:50])
    for r in rows:
        extra = r.extra_data or {}
        if extra.get('device') in pks:
            out.append({'when': r.timestamp, 'user': r.user, 'mode': extra.get('mode', ''), 'ok': bool(r.success),
                        'device_pk': extra.get('device'), 'session_confirmed': False,
                        'detail': r.description[:300]})
    return out[:10]


def _device_extras(device, ticket, requests, now) -> dict:
    from assets import device_workspace as ws
    from integrations.rmm_association import device_status
    sup = ws.support(device)
    alerts = []
    if sup['alerts']['state'] == ws.SUPPORTED:
        alerts = list(device.alerts.filter(organization_id=device.organization_id,
                                           triggered_at__gte=now - timedelta(days=RECENT_ALERT_DAYS))
                      .order_by('-triggered_at')[:5])
    changes = []
    if sup['software']['state'] == ws.SUPPORTED:
        for s in (device.software.filter(organization_id=device.organization_id,
                                         install_date__gte=now - timedelta(days=RECENT_CHANGE_DAYS))
                  .order_by('-install_date')[:5]):
            changes.append(f'Installed {s.name} {s.version}'.strip() + f' ({s.install_date:%Y-%m-%d})')
    rem0te_alerts = ws._rem0te_alerts(device)[:5]
    return {
        'status': device_status(device, now),
        'alerts': alerts,
        'alerts_support': sup['alerts'],
        'rem0te_alerts': rem0te_alerts,
        'changes': changes,
        'changes_support': sup['software'],
        'history': [r for r in requests if r.device_id == device.pk][:10],
        'patches': ws.patch_status(device, sup),
    }


def enrich(data: dict, user, ticket, assets) -> None:
    from integrations.rmm_association import exposed_devices, summary
    from psa_ai.models import RMMRequest
    now = timezone.now()
    requests = list(RMMRequest.objects.filter(ticket=ticket).select_related('actor', 'connection')
                    .order_by('-created_at')[:50])
    target_pks = {row['device'].pk for row in data['targets']}
    for row in data['targets']:
        row.update(_device_extras(row['device'], ticket, requests, now))
        row['asset'] = row['device'].linked_asset
        row['console'] = summary(row['device'], now)
    # Devices on the ticket that no paired RMM reaches: still listed, with
    # their RMM status if any RMM reports them, and why nothing can be done.
    devices = []
    for asset in assets:
        linked = list(exposed_devices(asset))
        devices.extend(linked)
        reachable = [d for d in linked if d.pk in target_pks]
        others = [summary(d, now) for d in linked if d.pk not in target_pks]
        data.setdefault('assets', []).append({
            'asset': asset, 'primary': asset.pk == ticket.related_asset_id, 'reachable': len(reachable),
            'unpaired': others,
        })
    data.setdefault('assets', [])
    data['launches'] = launches_for_ticket(ticket, devices)
    data['affected_choices'] = _affected_choices(ticket, assets)


def _affected_choices(ticket, assets):
    from assets.models import Asset
    have = {a.pk for a in assets}
    return [a for a in Asset.objects.filter(organization_id=ticket.organization_id).order_by('name')
            .only('id', 'name', 'hostname')[:500] if a.pk not in have]


# --- notes ----------------------------------------------------------------------

class NoteRefused(Exception):
    pass


def note_body(req) -> str:
    lines = [f'RMM {req.get_kind_display().lower()} on {req.device_name or "device"} via {req.connection.name}: '
             f'{req.get_status_display()}.']
    if req.diagnostic_label:
        lines.append(f'Diagnostic: {req.diagnostic_label}')
    if req.fix_title:
        lines.append(f'Action: {req.fix_title}')
    if req.remote_outcome:
        lines.append(f'Outcome reported by {req.connection.name}: {req.remote_outcome}')
    if req.status_note:
        lines.append(f'{req.connection.name} says: {req.status_note}')
    if req.error:
        lines.append(f'Error: {req.error}')
    if req.result_text:
        text = req.result_text[:NOTE_RESULT_CHARS]
        more = ' (truncated)' if len(req.result_text) > NOTE_RESULT_CHARS or req.result_truncated else ''
        lines.append(f'Result summary{more} — device output, treat as untrusted:\n{text}')
    lines.append(f'Request {req.pk}')
    return '\n'.join(lines)


def attach_note(user, ticket, request_id, http_request=None):
    """Add one request's outcome to the ticket as an internal note. Only a
    request made from this ticket; never customer-visible."""
    from audit.models import AuditLog
    from psa.models import TicketComment
    from psa_ai.models import RMMRequest
    try:
        req = RMMRequest.objects.select_related('connection').get(pk=request_id, ticket=ticket,
                                                                  organization_id=ticket.organization_id)
    except (RMMRequest.DoesNotExist, ValueError, TypeError, Exception):
        raise NoteRefused('That request is not one of this ticket\'s.')
    if req.status in ('created', 'pending'):
        raise NoteRefused('That request has no result yet.')
    comment = TicketComment.objects.create(ticket=ticket, author=user, body=note_body(req), is_internal=True,
                                           source='rmm')
    AuditLog.log(user=user, action='create', organization=ticket.organization, object_type='psa.TicketComment',
                 object_id=comment.pk, object_repr=f'RMM result note on {ticket.ticket_number}'[:255],
                 description=f'Attached the {req.get_kind_display().lower()} result from {req.connection.name} '
                             f'({req.device_name}) to {ticket.ticket_number} as an internal note'[:1000],
                 path=getattr(http_request, 'path', '') or '', extra_data={'request': str(req.pk)})
    return comment


# --- verify resolution ------------------------------------------------------------

OK, FAIL, UNKNOWN = 'ok', 'fail', 'unknown'


def verification(ticket) -> Dict:
    """Evidence, per device on the ticket, that the problem is resolved.
    Each check is ok / fail / unknown with the reason. Stored data only."""
    from integrations.rmm_association import device_status, exposed_devices
    from psa.affected import ticket_assets
    from psa_ai.models import Rem0teAlertTicket, RMMRequest
    now = timezone.now()
    out = []
    reqs = list(RMMRequest.objects.filter(ticket=ticket).order_by('-created_at'))
    for asset in ticket_assets(ticket):
        checks = []
        devices = list(exposed_devices(asset))
        if not devices:
            checks.append((UNKNOWN, 'No RMM reports this device, so ClientSt0r has no evidence. Verify it by hand.'))
        for d in devices:
            st = device_status(d, now)
            label = f'{d.connection.get_provider_type_display()} · {d.device_name}'
            if st['state'] == 'online':
                checks.append((OK, f'{label}: online, data fresh.'))
            elif st['state'] == 'offline':
                checks.append((FAIL, f'{label}: offline.'))
            else:
                checks.append((UNKNOWN, f'{label}: {st["detail"]}'))
            open_alerts = d.alerts.filter(organization_id=d.organization_id,
                                          status__in=('active', 'acknowledged')).count()
            if open_alerts:
                checks.append((FAIL, f'{label}: {open_alerts} open alert{"s" if open_alerts != 1 else ""}.'))
            for r in [r for r in reqs if r.device_id == d.pk]:
                if r.status not in r.TERMINAL and r.status != 'approved':
                    checks.append((FAIL, f'{label}: {r.get_kind_display()} still waiting ({r.get_status_display()}).'))
                elif r.status == 'approved':
                    checks.append((FAIL, f'{label}: approved action not finished yet.'))
            last_fix = next((r for r in reqs if r.device_id == d.pk and r.kind == RMMRequest.KIND_FIX), None)
            if last_fix is not None:
                if last_fix.status == 'succeeded':
                    checks.append((OK, f'{label}: last action reported succeeded by {last_fix.connection.name}.'))
                elif last_fix.status in ('failed', 'rejected', 'expired', 'unavailable'):
                    checks.append((FAIL, f'{label}: last action {last_fix.get_status_display().lower()}.'))
        out.append({'asset': asset, 'checks': [{'state': s, 'text': t} for s, t in checks]})
    for row in Rem0teAlertTicket.objects.filter(ticket=ticket, organization_id=ticket.organization_id):
        state = OK if row.state == 'resolved' else FAIL
        out.append({'asset': None, 'checks': [{'state': state, 'text': f'Rem0te alert "{row.title}": '
                                                                       f'{row.state or "unknown"}.'}]})
    states = [c['state'] for row in out for c in row['checks']]
    return {'rows': out, 'all_ok': bool(states) and all(s == OK for s in states),
            'failed': states.count(FAIL), 'unknown': states.count(UNKNOWN) + (0 if states else 1),
            'checked_at': now}


def verification_text(v) -> str:
    lines = ['Resolution verification before closing:']
    for row in v['rows']:
        name = row['asset'].name if row['asset'] is not None else 'Alerts'
        for c in row['checks']:
            mark = {'ok': 'OK', 'fail': 'NOT OK', 'unknown': 'UNKNOWN'}[c['state']]
            lines.append(f'- [{mark}] {name}: {c["text"]}')
    if not v['rows']:
        lines.append('- [UNKNOWN] No devices on this ticket.')
    return '\n'.join(lines)
