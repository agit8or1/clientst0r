"""
Device Workspace (ClientSt0r ↔ RMM Phase 3): one page per asset that gathers
what every linked RMM reports about it, what ClientSt0r knows about it
(tickets, docs, runbooks, credentials) and what a technician can do next.

Rules this module keeps:

  * One authoritative record: the Asset. RMM devices are linked external
    records (several providers may manage one asset); nothing here copies
    their inventory into new tables. Everything is read from what the sync
    already stored (RMMDevice / RMMAlert / RMMSoftware, Rem0te alert events),
    so the page never calls an RMM while it renders.
  * Every value says how old it is. A device whose data is older than its
    connection's stale threshold is shown as stale, never as current.
  * What a provider doesn't supply is shown as unsupported, with whose gap
    it is — not as "none", "no" or an empty list. Restart pending is
    "unknown" unless something reported it.
  * Only the asset's own customer's devices (rmm_association.exposed_devices)
    and records. Technicians only: the view checks that before calling here.
  * Actions are not decided here. The toolbar asks the same server-side
    checks the ticket routes enforce (psa_ai.services.rmm_actions
    .action_state) and the routes check again on POST; this module only
    explains why something is disabled.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Dict, List, Optional

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

SUPPORTED, UNSUPPORTED, NOT_SYNCED, NO_DATA = 'supported', 'unsupported', 'not_synced', 'no_data'

# Raw field names are read per provider (integrations/rmm_fields.py), never
# guessed across providers; services come from the opt-in kept lists
# (integrations/rmm_snapshots.py).

MAX_ROWS = 200
RECENT_CHANGE_DAYS = 14


# --- small helpers -------------------------------------------------------------

def _as_dt(value) -> Optional[datetime]:
    """A timestamp from raw RMM data: ISO text or Unix seconds/milliseconds."""
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        secs = float(value) / (1000.0 if value > 10 ** 11 else 1.0)
        try:
            return datetime.fromtimestamp(secs, tz=dt_timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    dt = parse_datetime(str(value)[:40])
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


def _text(value, limit=200) -> str:
    return str(value if value is not None else '')[:limit]


def provider_of(device):
    from integrations.providers.rmm import RMM_PROVIDER_REGISTRY
    return RMM_PROVIDER_REGISTRY.get(device.connection.provider_type)


def provider_label(device) -> str:
    return device.connection.get_provider_type_display()


# --- what each provider supplies --------------------------------------------------

def support(device) -> Dict[str, Dict[str, str]]:
    """{data kind: {'state', 'detail'}} for one linked device.

    `supported` — the integration supplies it (it may still be empty).
    `not_synced` — it could, but the connection doesn't sync it.
    `unsupported` — this integration doesn't give it to ClientSt0r.
    """
    from integrations import rmm_fields
    p = provider_of(device)
    conn = device.connection
    label = provider_label(device)
    out = {}

    def put(kind, state, detail=''):
        out[kind] = {'state': state, 'detail': detail}

    # Installed software.
    if conn.provider_type == 'rem0te':
        put('software', UNSUPPORTED, "Rem0te's inventory API doesn't share installed software with ClientSt0r.")
    elif p is not None and getattr(p, 'supports_software', False):
        if conn.sync_software:
            put('software', SUPPORTED)
        else:
            put('software', NOT_SYNCED, f'Switch on Sync Software on the {conn.name} connection to collect it.')
    else:
        put('software', UNSUPPORTED, f"{label}'s integration doesn't supply installed software.")

    # Alerts.
    if conn.provider_type == 'rem0te':
        from integrations.ticket_rmm import advertised
        if 'alerts' in advertised(conn):
            put('alerts', SUPPORTED, 'From Rem0te alert events (only alerts its notification policy offers).')
        else:
            put('alerts', UNSUPPORTED, 'Rem0te sends alerts only through a live ticket pairing with alert events.')
    elif p is not None and getattr(p, 'supports_alerts', False):
        put('alerts', SUPPORTED if conn.sync_alerts else NOT_SYNCED,
            '' if conn.sync_alerts else f'Switch on Sync Alerts on the {conn.name} connection.')
    else:
        put('alerts', UNSUPPORTED, f"{label}'s integration doesn't supply alerts.")

    # Services: kept (opt-in) only where the provider's client already
    # returns them. Processes and Windows events: no provider's client
    # returns them; each says what it would take.
    if p is not None and getattr(p, 'supports_services', False):
        if getattr(conn, 'sync_services', False):
            put('services', SUPPORTED, f'Kept from {label} at each sync (latest list only, for '
                                       f'{_retention_days()} days).')
        else:
            put('services', NOT_SYNCED, f'Switch on Collect services on the {conn.name} connection to keep them.')
    else:
        put('services', UNSUPPORTED, rmm_fields.list_gap(conn.provider_type, 'services', f"{label}'s"))
    for kind in ('processes', 'events'):
        put(kind, UNSUPPORTED, rmm_fields.list_gap(conn.provider_type, kind, f"{label}'s"))

    # Patches.
    if conn.provider_type == 'rem0te':
        put('patches', SUPPORTED, 'From the patch summary on Rem0te restart-pending alerts (contract revision 2).')
    elif conn.provider_type in rmm_fields.PATCH_SOURCE:
        put('patches', SUPPORTED, f'From {rmm_fields.PATCH_SOURCE[conn.provider_type]}.')
    else:
        put('patches', UNSUPPORTED, f"{label}'s integration doesn't report patch status to ClientSt0r.")
    return out


def _retention_days():
    from integrations.rmm_snapshots import RETENTION_DAYS
    return RETENTION_DAYS


# --- per-device facts --------------------------------------------------------------

def rem0te_patch_summary(device) -> Optional[dict]:
    """The latest patch summary Rem0te sent for this computer (on a
    restart-pending alert), with when it arrived, or None. Matched by
    Rem0te's immutable endpoint id on this device's own connection, never
    by name. Only the contract's fields, as text."""
    if device.connection.provider_type != 'rem0te' or not device.external_id:
        return None
    from psa_ai.models import Rem0teAlertEvent
    try:
        rows = list(Rem0teAlertEvent.objects.filter(connection=device.connection,
                                                    body__alert__rem0te_endpoint_id=device.external_id)
                    .order_by('-sequence')[:20])
    except Exception:  # JSON lookups unavailable on this database: scan recent events
        rows = [e for e in Rem0teAlertEvent.objects.filter(connection=device.connection).order_by('-sequence')[:500]
                if ((e.body or {}).get('alert') or {}).get('rem0te_endpoint_id') == device.external_id][:20]
    for row in rows:
        ps = ((row.body or {}).get('alert') or {}).get('patch_summary')
        if not isinstance(ps, dict):
            continue
        kbs = lambda k: [_text(x, 16) for x in (ps.get(k) or []) if isinstance(x, str)][:20]  # noqa: E731
        return {
            'received_at': row.received_at,
            'evidence_source': _text(ps.get('evidence_source'), 30),
            'evidence_at': _as_dt(ps.get('evidence_at')),
            'evidence_age_hours': ps.get('evidence_age_hours'),
            'freshness': _text(ps.get('freshness'), 10),
            'last_boot_at': _as_dt(ps.get('last_boot_at')),
            'managed_by': _text(ps.get('managed_by'), 40),
            'managers': [_text(m, 64) for m in (ps.get('managers') or []) if isinstance(m, str)][:4],
            'reboot_required': ps.get('reboot_required') if isinstance(ps.get('reboot_required'), bool) else None,
            'pending_count': ps.get('pending_count') if isinstance(ps.get('pending_count'), int) else None,
            'pending_kbs': kbs('pending_kbs'), 'confirmed_kbs': kbs('confirmed_kbs'),
            'failed_kbs': kbs('failed_kbs'), 'awaiting_confirmation_kbs': kbs('awaiting_confirmation_kbs'),
            'deploy_available': ps.get('deploy_available') if isinstance(ps.get('deploy_available'), bool) else None,
        }
    return None


def patch_status(device, sup, facts=None) -> dict:
    """Restart pending and patch posture. `reboot` is True / False / None
    (unknown) — never False just because nothing was reported."""
    if sup['patches']['state'] != SUPPORTED:
        return {'state': UNSUPPORTED, 'detail': sup['patches']['detail'], 'reboot': None}
    if device.connection.provider_type == 'rem0te':
        ps = rem0te_patch_summary(device)
        if ps is None:
            return {'state': NO_DATA, 'reboot': None, 'source': 'Rem0te',
                    'detail': 'No patch summary received yet. Rem0te sends one with a restart-pending alert; '
                              "its Patches tab has the computer's full patch status."}
        return {'state': SUPPORTED, 'reboot': ps['reboot_required'], 'summary': ps, 'source': 'Rem0te patch summary',
                'as_of': ps['evidence_at'] or ps['received_at']}
    from integrations import rmm_fields
    f = facts if facts is not None else rmm_fields.facts(device)
    fields = []
    if f.get('last_patched') is not None:
        fields.append(('Last patched', f['last_patched'].strftime('%Y-%m-%d %H:%M')))
    fields.extend((_text(k, 40), _text(v, 60)) for k, v in (f.get('patch_fields') or [])[:8])
    return {'state': SUPPORTED, 'reboot': f.get('reboot'), 'fields': fields,
            'reboot_detail': f['unsupported'].get('reboot', ''),
            'source': provider_label(device), 'as_of': device.data_refreshed_at}


def _ips(device, facts) -> List[str]:
    ips = list(facts.get('ips') or [])[:10]
    if device.ip_address and str(device.ip_address) not in ips:
        ips.insert(0, str(device.ip_address))
    return ips


def _services(device, sup, now) -> dict:
    """The kept service list (opt-in), as text rows with when it was
    collected; nothing unless services are supported here."""
    empty = {'rows': [], 'as_of': None, 'truncated': False, 'total': 0}
    if sup['services']['state'] != SUPPORTED:
        return empty
    from integrations.rmm_snapshots import latest
    snap = latest(device, 'services', now=now)
    if snap is None:
        return empty
    rows = []
    for s in (snap.items or [])[:MAX_ROWS]:
        if not isinstance(s, dict):
            continue
        name = _text(s.get('display_name') or s.get('name'), 120)
        extra = ', '.join(x for x in (_text(s.get('status'), 20), _text(s.get('start_type'), 20)) if x)
        rows.append(name + (f' — {extra}' if extra else ''))
    return {'rows': rows, 'as_of': snap.collected_at, 'total': snap.item_count,
            'truncated': snap.truncated or snap.item_count > len(rows)}


def _uptime(boot: Optional[datetime], status_state: str, now) -> str:
    if boot is None:
        return ''
    if status_state != 'online':
        return ''  # an uptime for a machine we can't see now would be invented
    delta = now - boot
    if delta.total_seconds() < 0:
        return ''
    days, rem = divmod(int(delta.total_seconds()), 86400)
    return f'{days}d {rem // 3600}h'


def device_view(device, *, show_user: bool, now=None) -> dict:
    """Everything the workspace shows about one linked RMM device."""
    from integrations import rmm_fields
    from integrations.rmm_association import console_label, console_link, device_hardware, device_status, \
        stale_after
    now = now or timezone.now()
    status = device_status(device, now)
    sup = support(device)
    hw = device_hardware(device)
    facts = rmm_fields.facts(device)
    boot = facts['last_boot']
    agent_version = facts['agent_version']
    logged_in = facts['logged_in']
    services = _services(device, sup, now)
    software = []
    if sup['software']['state'] == SUPPORTED:
        software = list(device.software.filter(organization_id=device.organization_id)
                        .order_by('name')[:MAX_ROWS])
    alerts = []
    if sup['alerts']['state'] == SUPPORTED:
        alerts = list(device.alerts.filter(organization_id=device.organization_id,
                                           status__in=('active', 'acknowledged')).order_by('-triggered_at')[:20])
    rem0te_alerts = _rem0te_alerts(device)
    since = now - timedelta(days=RECENT_CHANGE_DAYS)
    recent_software = [s for s in software if s.install_date and s.install_date >= since][:20]
    return {
        'device': device,
        'provider': provider_label(device),
        'connection': device.connection,
        'status': status,
        'stale_after_hours': int(stale_after(device.connection).total_seconds() // 3600),
        'last_heartbeat': device.last_seen,
        'data_refreshed_at': device.data_refreshed_at,
        'agent_version': _text(agent_version, 60) if agent_version is not None else '',
        'logged_in': (_text(logged_in, 120) if (show_user and logged_in is not None) else ''),
        'logged_in_hidden': bool(logged_in is not None and not show_user),
        'hardware': hw,
        'last_boot': boot,
        'uptime': _uptime(boot, status['state'], now),
        'disks': facts['disks'],
        'nics': facts['nics'], 'ips': _ips(device, facts), 'public_ip': facts['public_ip'] or '',
        'gaps': facts['unsupported'],  # fact -> why this provider doesn't supply it
        'support': sup,
        'software': software,
        'software_total': device.software.filter(organization_id=device.organization_id).count()
        if sup['software']['state'] == SUPPORTED else 0,
        'recent_software': recent_software,
        'services': services['rows'],
        'services_as_of': services['as_of'],
        'services_total': services['total'],
        'services_truncated': services['truncated'],
        'events': [],  # no provider's client returns them (support() says why)
        'patches': patch_status(device, sup, facts),
        'alerts': alerts,
        'rem0te_alerts': rem0te_alerts,
        'alert_count': len(alerts) + len([r for r in rem0te_alerts if r.state != 'resolved']),
        'console_url': console_link(device),
        'console_label': console_label(device),
        'refresh': _refresh_state(device),
        'external_id': device.external_id,
    }


def _refresh_state(device) -> dict:
    """Whether "Refresh from RMM" can run for this device, decided from
    stored data only (the POST route checks permission and runs it)."""
    from integrations.rmm_refresh import availability
    ok, reason = availability(device)
    return {'available': ok, 'reason': reason}


def _rem0te_alerts(device) -> list:
    if device.connection.provider_type != 'rem0te' or not device.external_id:
        return []
    from psa_ai.models import Rem0teAlertTicket
    return list(Rem0teAlertTicket.objects.filter(connection=device.connection, rem0te_endpoint_id=device.external_id,
                                                 organization_id=device.organization_id)
                .select_related('ticket').order_by('-created_at')[:10])


# --- asset-level records -------------------------------------------------------------

def related_tickets(asset, limit=15) -> list:
    from psa.affected import tickets_for_asset
    return list(tickets_for_asset(asset).select_related('status', 'priority', 'assigned_to')
                .order_by('-created_at')[:limit])


def related_docs(asset) -> list:
    from docs.models import Document
    from .models import Relationship
    ids = set(Relationship.objects.filter(organization_id=asset.organization_id, source_type='asset',
                                          source_id=asset.pk, target_type='document')
              .values_list('target_id', flat=True))
    ids |= set(Relationship.objects.filter(organization_id=asset.organization_id, target_type='asset',
                                           target_id=asset.pk, source_type='document')
               .values_list('source_id', flat=True))
    for attr in ('profile_document_id', 'ai_document_id'):
        if getattr(asset, attr, None):
            ids.add(getattr(asset, attr))
    if not ids:
        return []
    return list(Document.objects.filter(pk__in=ids, organization_id=asset.organization_id).order_by('title')[:30])


def related_runbooks(asset) -> list:
    from django.db.models import Q
    from processes.models import Process
    return list(Process.objects.filter(stages__linked_asset=asset)
                .filter(Q(organization_id=asset.organization_id) | Q(is_global=True))
                .distinct().order_by('title')[:20])


def related_credentials(asset, user) -> dict:
    """Titles of the vault entries linked to this asset — never a secret.
    Revealing goes through the vault's own page and its reveal / approval
    flow. Without vault access at this customer only a count is shown."""
    from accounts.permission_utils import has_perm_for_org
    from vault.models import Password, PasswordRelation
    ids = PasswordRelation.objects.filter(relation_type='asset', relation_id=asset.pk).values_list('password_id',
                                                                                                   flat=True)
    qs = Password.objects.filter(pk__in=list(ids), organization_id=asset.organization_id, is_personal=False)
    if not has_perm_for_org(user, asset.organization_id, 'vault_view'):
        return {'allowed': False, 'count': qs.count(), 'entries': []}
    return {'allowed': True, 'count': qs.count(),
            'entries': list(qs.only('id', 'title', 'username', 'organization_id').order_by('title')[:30])}


def remediation_history(devices, limit=30) -> list:
    """ClientSt0r's requests to an RMM for these devices (handoffs,
    diagnostics, fix referrals / action proposals), newest first."""
    from psa_ai.models import RMMRequest
    if not devices:
        return []
    org_ids = {d.organization_id for d in devices}
    return list(RMMRequest.objects.filter(device__in=devices, organization_id__in=org_ids)
                .select_related('ticket', 'actor', 'connection').order_by('-created_at')[:limit])


def launch_history(devices, limit=15) -> list:
    """Remote launches ClientSt0r handed out for these devices (audit log).
    A launch is a link the RMM issued; whether a session followed is the
    RMM's to say, and no RMM tells ClientSt0r — so each is "not confirmed"."""
    from audit.models import AuditLog
    if not devices:
        return []
    pks = {d.pk for d in devices}
    org_ids = {d.organization_id for d in devices}
    rows = (AuditLog.objects.filter(object_type='psa_ai.RemoteLaunch', organization_id__in=org_ids)
            .order_by('-timestamp')[:200])
    out = []
    for r in rows:
        extra = r.extra_data or {}
        if extra.get('device') in pks:
            out.append({'when': r.timestamp, 'user': r.user, 'mode': extra.get('mode', ''),
                        'ok': bool(r.success), 'description': r.description, 'device_pk': extra.get('device'),
                        'session_confirmed': False})
        if len(out) >= limit:
            break
    return out


# --- the toolbar ---------------------------------------------------------------------

def _btn(key, label, enabled, reason='', href='', post=None, icon='', note=''):
    return {'key': key, 'label': label, 'enabled': bool(enabled), 'reason': reason, 'href': href, 'post': post,
            'icon': icon, 'note': note}


def toolbar(user, asset, primary: Optional[dict], ticket=None, psa_on=True) -> List[dict]:
    """CONNECT | DIAGNOSE | RUN APPROVED ACTION | PATCHES | CREATE TICKET | MORE.

    Device actions are requested from a ticket (that is where they are
    authorized, recorded and audited), so without a ticket in context they
    point to one instead of acting. `primary` is the selected device's
    `device_view`."""
    from psa_ai.services import rmm_actions
    out = []
    target = None
    if primary is not None and ticket is not None:
        try:
            target = rmm_actions.find_target(ticket, primary['device'].pk)
        except rmm_actions.ActionRefused:
            target = None
    no_device = 'No RMM manages this asset.'
    need_ticket = ('Requested from a ticket so it is authorized and recorded there: open this device from a '
                   'ticket, or create one.')

    # CONNECT
    if primary is None:
        out.append(_btn('connect', 'Connect', False, no_device, icon='fa-desktop'))
    elif target is not None:
        ok, reason, grant = rmm_actions.action_state(user, ticket, target, 'remote_view')
        okc, reasonc, grantc = rmm_actions.action_state(user, ticket, target, 'remote_control')
        if okc or ok:
            mode = 'control' if okc else 'view'
            g = grantc if okc else grant
            out.append(_btn('connect', ('Request ' if g == 'request' else '') + ('control' if okc else 'view'),
                            True, post={'url': reverse('ticket_rmm:launch', args=[ticket.ticket_number]),
                                        'device': primary['device'].pk, 'mode': mode},
                            icon='fa-desktop',
                            note=f'{primary["connection"].name} authorizes the session. ClientSt0r records the '
                                 'launch only; it is not told whether a session started.'))
        elif primary['console_url']:
            out.append(_btn('connect', primary['console_label'], True, href=primary['console_url'], icon='fa-desktop',
                            note=f'Opens {primary["provider"]}, which applies its own sign-in and launch policy. '
                                 f'Remote launch from this ticket: {reason}'))
        else:
            out.append(_btn('connect', 'Connect', False, reason, icon='fa-desktop'))
    elif primary['console_url']:
        out.append(_btn('connect', primary['console_label'], True, href=primary['console_url'], icon='fa-desktop',
                        note=f'Opens {primary["provider"]}, which applies its own sign-in and launch policy. '
                             'ClientSt0r is not told whether a session started.'))
    else:
        out.append(_btn('connect', 'Connect', False,
                        f"{primary['provider']} gives ClientSt0r no console link for this device. " + need_ticket,
                        icon='fa-desktop'))

    # DIAGNOSE
    if primary is None:
        out.append(_btn('diagnose', 'Diagnose', False, no_device, icon='fa-stethoscope'))
    elif ticket is None:
        out.append(_btn('diagnose', 'Diagnose', False, need_ticket, icon='fa-stethoscope'))
    elif target is None:
        out.append(_btn('diagnose', 'Diagnose', False, 'This device is not reachable from the ticket through a paired '
                                                       'RMM of this customer.', icon='fa-stethoscope'))
    else:
        ok, reason, _ = rmm_actions.action_state(user, ticket, target, 'diagnostic')
        out.append(_btn('diagnose', 'Diagnose (read-only)', ok, reason,
                        href=reverse('psa:ticket_detail', args=[ticket.ticket_number]) + '#ticket-rmm-panel',
                        icon='fa-stethoscope'))

    # RUN APPROVED ACTION
    if primary is None:
        out.append(_btn('action', 'Run approved action', False, no_device, icon='fa-shield-halved'))
    elif ticket is None:
        out.append(_btn('action', 'Run approved action', False, need_ticket, icon='fa-shield-halved'))
    elif target is None:
        out.append(_btn('action', 'Run approved action', False, 'This device is not reachable from the ticket '
                                                                 'through a paired RMM of this customer.',
                        icon='fa-shield-halved'))
    else:
        ok, reason, _ = rmm_actions.action_state(user, ticket, target, 'fix_low')
        okh, reasonh, _ = rmm_actions.action_state(user, ticket, target, 'fix_high')
        out.append(_btn('action', 'Request approved action', ok or okh, reason or reasonh,
                        href=reverse('psa:ticket_detail', args=[ticket.ticket_number]) + '#ticket-rmm-panel',
                        icon='fa-shield-halved',
                        note=f'Approval required in {primary["connection"].name}. ClientSt0r proposes; it never '
                             'approves or runs anything.'))

    # PATCHES
    if primary is None:
        out.append(_btn('patches', 'Patches', False, no_device, icon='fa-bandage'))
    else:
        p = primary['patches']
        out.append(_btn('patches', 'Patches', p['state'] != UNSUPPORTED, p.get('detail', ''), href='#ws-patches',
                        icon='fa-bandage'))

    # CREATE TICKET
    if not psa_on:
        out.append(_btn('ticket', 'Create ticket', False, 'The service desk is not switched on for this customer.',
                        icon='fa-ticket'))
    else:
        from urllib.parse import urlencode
        q = urlencode({'asset': asset.pk, 'subject': f'{asset.name}: '})
        out.append(_btn('ticket', 'Create ticket', True, href=reverse('psa:ticket_create') + '?' + q,
                        icon='fa-ticket'))
    return out
