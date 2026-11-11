"""
RMM handoffs, read-only diagnostics, remote launch and fix referrals from a
ticket (docs/contracts/ticket-rmm-v1, Phase 56.5 / 56.6).

These are not AI features. They work with AI switched off; they need PSA,
technician access (Phase 57 — the RMM, Remote access and Fixes groups) and
a paired RMM that advertises the matching capability.

Targets. A ticket can reach a device only through a verified, same-business
association: the ticket's own asset, linked to an RMMDevice whose customer
is settled and is the ticket's customer, on a connection that is a live
ticket-rmm-v1 pairing of that same customer with a pinned tenant
(`targets()`). The browser names a target by its position in that list's
device IDs; an ID outside it is refused. The RMM's device ID is never taken
from the browser, a hostname or model output.

What ClientSt0r does and doesn't do:

  * Handoff — sends the ticket's redacted context (the same evidence and
    redaction rules as "Analyze ticket", previewed first). Shown as Sent only
    when the RMM confirms receipt with a signed `handoff.received` event.
  * Diagnostic — asks for one named read-only diagnostic from the RMM's own
    advertised list. The result arrives by signed event, is sanitised,
    size-limited and kept as staff-only evidence on the request (never a
    ticket comment, never customer-visible), and counts toward theft
    detection's diagnostic bytes.
  * Remote launch — asks the RMM for a short-lived launch URL, checks it
    against the connection's console hosts, redirects the technician and
    forgets it. The launch is audited; the URL is never stored or logged.
  * Fix referral — records a referral; the RMM's signed status updates move
    it (received / approved / rejected / running / succeeded / failed).
    ClientSt0r never executes anything, never marks a fix approved itself,
    and no status can close the ticket or send a customer reply: events only
    ever update the RMMRequest row.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import evidence as ev, processor

MAX_RESULT_BYTES = 32 * 1024
MAX_NOTE_CHARS = 1000
MAX_FIX_CHARS = 2000
LAUNCH_MAX_LIFETIME = timedelta(minutes=10)
EXPIRE_AFTER = {'handoff': timedelta(hours=1), 'diagnostic': timedelta(hours=1),
                'fix_referral': timedelta(days=14)}

# Technician-access capability for each action.
ACTION_CAPABILITY = {
    'handoff': 'rmm_handoff',
    'diagnostic': 'diagnostics_readonly',
    'remote_view': 'remote_view',
    'remote_control': 'remote_control',
    'fix_low': 'fix_request_low',
    'fix_high': 'fix_request_high',
}
# What the target's pairing must advertise for each action.
ACTION_ADVERTISED = {
    'handoff': 'rmm_handoff',
    'diagnostic': 'diagnostics_readonly',
    'remote_view': 'remote_view',
    'remote_control': 'remote_control',
    'fix_low': 'signed_actions',
    'fix_high': 'signed_actions',
}
# RMM permission action (rmm_permissions.catalog) for each action. The
# decision includes the technician-access capability above, plus role tiers,
# overrides and second-person approval.
RMM_ACTION = {
    'handoff': 'rmm.handoff',
    'diagnostic': 'diagnostics.run',
    'remote_view': 'remote.request_support',
    'remote_control': 'remote.request_control',
    'fix_low': 'remediation.request_low',
    'fix_high': 'remediation.request_high',
}
ACTION_LABEL = {
    'handoff': 'Send to RMM', 'diagnostic': 'Run diagnostic', 'remote_view': 'View session',
    'remote_control': 'Control session', 'fix_low': 'Refer a fix', 'fix_high': 'Refer higher-risk work',
}

# (kind, event type) → (new status, statuses it may move from).
TRANSITIONS: Dict[Tuple[str, str], Tuple[str, set]] = {
    ('handoff', 'handoff.received'): ('sent', {'pending'}),
    ('handoff', 'handoff.rejected'): ('rejected', {'pending'}),
    ('diagnostic', 'diagnostic.accepted'): ('received', {'pending'}),
    ('diagnostic', 'diagnostic.running'): ('running', {'pending', 'received'}),
    ('diagnostic', 'diagnostic.completed'): ('completed', {'pending', 'received', 'running'}),
    ('diagnostic', 'diagnostic.failed'): ('failed', {'pending', 'received', 'running'}),
    ('diagnostic', 'diagnostic.rejected'): ('rejected', {'pending', 'received'}),
    ('fix_referral', 'fix.received'): ('received', {'pending'}),
    ('fix_referral', 'fix.approved'): ('approved', {'pending', 'received'}),
    ('fix_referral', 'fix.rejected'): ('rejected', {'pending', 'received'}),
    ('fix_referral', 'fix.running'): ('running', {'approved'}),
    ('fix_referral', 'fix.succeeded'): ('succeeded', {'approved', 'running'}),
    ('fix_referral', 'fix.failed'): ('failed', {'approved', 'running'}),
}
REQUEST_EVENT_TYPES = {t for (_k, t) in TRANSITIONS}

_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


class ActionRefused(Exception):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.message, self.status = message, status


@dataclass
class Target:
    device: object
    connection: object

    @property
    def tenant_id(self):
        from integrations.ticket_rmm import settings
        return settings(self.connection)['tenant_id']


# --- targets -----------------------------------------------------------------

def targets(ticket) -> List[Target]:
    """Devices this ticket may reach: verified, same-customer, same-tenant.

    Every device of every asset the ticket is about (psa.affected
    .ticket_assets: the primary asset, then the affected devices a
    technician added), each through its own verified RMM link."""
    from integrations.models import RMMDevice
    from integrations.rmm_association import exposed_devices
    from integrations.ticket_rmm import is_processor, settings
    from psa.affected import ticket_assets
    out = []
    for asset in ticket_assets(ticket):
        if asset.organization_id != ticket.organization_id:
            continue
        for d in exposed_devices(asset).order_by('pk'):
            conn = d.connection
            if (d.organization_id != ticket.organization_id or conn.organization_id != ticket.organization_id
                    or d.linked_asset_id != asset.pk or not conn.is_active or not is_processor(conn)):
                continue
            if d.link_status in (RMMDevice.LINK_REVIEW, RMMDevice.LINK_UNLINKED) or not d.external_id:
                continue
            # rem0te reports each computer's business; it must be the pinned tenant.
            if conn.provider_type == 'rem0te' and d.client_id and d.client_id != settings(conn)['tenant_id']:
                continue
            out.append(Target(d, conn))
    return out


def find_target(ticket, device_pk) -> Target:
    try:
        pk = int(device_pk)
    except (TypeError, ValueError):
        raise ActionRefused('Choose one of the devices linked to this ticket.', 400)
    for t in targets(ticket):
        if t.device.pk == pk:
            return t
    raise ActionRefused('That device is not linked to this ticket through a paired RMM of this customer.', 404)


# --- availability ------------------------------------------------------------

def _decision(user, ticket, action, target=None):
    from rmm_permissions import can
    return can(user, ticket.organization, RMM_ACTION[action], device=target.device if target else None,
               ticket=ticket)


def authorize(user, ticket, target: Target, action, request=None, digest=''):
    """The audited permission check right before an RMM operation runs.
    Needs approval → an approval request is filed and the operation is
    refused until a second person approves it."""
    from rmm_permissions import rmm_action
    d = rmm_action(user, ticket.organization, RMM_ACTION[action], device=target.device, ticket=ticket,
                   digest=digest, request=request)
    if d.permitted_now:
        return d
    if not d.allowed:
        raise ActionRefused(d.reason)
    from rmm_permissions.approvals import request_approval
    a = request_approval(user, ticket.organization, RMM_ACTION[action], device=target.device, ticket=ticket,
                         digest=digest, summary=f'{ACTION_LABEL[action]} on {ticket.ticket_number}',
                         request=request)
    raise ActionRefused(f'{d.reason} Approval #{a.pk} has been requested; try again once it is approved.', 409)


def action_state(user, ticket, target: Target, action) -> Tuple[bool, str, str]:
    """(usable, reason when not, grant 'allowed'|'request'). The access
    decision is about the target's own asset (its device class decides
    whether read-only diagnostics cover it), not the ticket's primary one."""
    from integrations.ticket_rmm import advertised
    d = _decision(user, ticket, action, target)
    remote = action in ('remote_view', 'remote_control')
    if not d.allowed or (d.grant == 'request' and not remote):
        return False, d.reason, ''
    if ACTION_ADVERTISED[action] not in advertised(target.connection):
        return False, f"{target.connection.name} doesn't offer this.", ''
    if action == 'diagnostic' and not diagnostics_for(target):
        return False, f'{target.connection.name} lists no read-only diagnostics for this device.', ''
    if action in NEEDS_AGENT:
        offline = agent_offline_reason(target.device)
        if offline:
            return False, offline, ''
    return True, '', ('request' if d.grant == 'request' else 'allowed')


def _usable_or_refuse(user, ticket, target: Target, action, request=None) -> str:
    """action_state for an operation about to run: a refusal is audited."""
    ok, reason, grant = action_state(user, ticket, target, action)
    if not ok:
        from rmm_permissions import audit_denial
        audit_denial(user, ticket.organization, RMM_ACTION[action], reason, device=target.device, request=request)
        raise ActionRefused(reason)
    return grant


# Actions that need the device's agent to answer now. A fix referral waits
# for approval in the RMM and is not refused here for an offline agent: the
# RMM decides (Rem0te answers ENDPOINT_NOT_READY when it can't run it).
NEEDS_AGENT = {'diagnostic', 'remote_view', 'remote_control'}


def agent_offline_reason(device) -> str:
    """Why the agent can't be reached, from fresh synced data only. Stale or
    unknown status is not treated as offline: the RMM answers for itself."""
    from integrations.rmm_association import device_status
    st = device_status(device)
    if st['state'] != 'offline':
        return ''
    when = timezone.localtime(device.last_seen).strftime('%Y-%m-%d %H:%M') if device.last_seen else 'unknown'
    return f'The agent is offline (last check-in {when}).'


def diagnostics_for(target: Target) -> List[dict]:
    from integrations.ticket_rmm import diagnostics
    dtype = (target.device.device_type or '').lower()
    out = []
    for diag in diagnostics(target.connection):
        classes = diag.get('device_classes') or []
        if classes and dtype not in classes and 'any' not in classes:
            continue
        out.append(diag)
    return out


def panel(user, ticket) -> dict:
    """Everything the ticket's RMM panel shows a technician."""
    from psa_ai.models import RMMRequest
    rows = []
    for t in targets(ticket):
        actions = {}
        for action in ACTION_CAPABILITY:
            ok, reason, grant = action_state(user, ticket, t, action)
            actions[action] = {'ok': ok, 'reason': reason, 'grant': grant, 'label': ACTION_LABEL[action]}
        rows.append({'device': t.device, 'connection': t.connection, 'actions': actions,
                     'diagnostics': diagnostics_for(t) if actions['diagnostic']['ok'] else [],
                     'catalog': _catalog(t)})
    from psa.affected import ticket_assets
    assets = ticket_assets(ticket)
    no_target_reason = ''
    if not rows:
        if not assets:
            no_target_reason = 'Set the asset this ticket is about to reach its device through a paired RMM.'
        else:
            no_target_reason = ('No paired RMM manages the devices on this ticket for this customer, so handoffs, '
                                'diagnostics, remote sessions and fix referrals are not available.')
    requests = list(RMMRequest.objects.filter(ticket=ticket).select_related('actor', 'connection')[:20])
    _refresh_rem0te(requests)
    suggestions = analysis_suggestions(ticket) if any(r['actions']['fix_low']['ok'] or r['actions']['fix_high']['ok']
                                                      for r in rows) else []
    data = {'targets': rows, 'requests': requests, 'no_target_reason': no_target_reason,
            'suggestions': suggestions}
    from . import device_panel
    device_panel.enrich(data, user, ticket, assets)
    return data


def _catalog(target: Target) -> List[dict]:
    """Rem0te only: the catalog actions it advertised that ClientSt0r knows."""
    if target.connection.provider_type != 'rem0te':
        return []
    from integrations.rem0te import pairing
    return pairing.proposable_actions(target.connection)


def _refresh_rem0te(requests):
    """Rem0te proposals have no status callbacks: read open ones (rate-limited)."""
    from integrations.rem0te import actions as rem0te_actions
    for r in requests:
        if r.connection.provider_type == 'rem0te' and r.kind == 'fix_referral' and r.status not in r.TERMINAL:
            try:
                rem0te_actions.refresh(r)
            except Exception:
                pass


def analysis_suggestions(ticket) -> List[dict]:
    """Suggested checks from this ticket's latest successful analyses, for
    "Refer a fix". Referenced by job and index; the text is re-read from the
    stored result on submit, never taken from the browser."""
    from psa_ai.models import AnalysisRun
    out = []
    runs = (AnalysisRun.objects.filter(job__ticket=ticket, status='succeeded')
            .select_related('job').order_by('-finished_at', '-pk')[:3])
    for run in runs:
        for n, check in enumerate((run.result or {}).get('suggested_checks') or []):
            text = (check or {}).get('text') if isinstance(check, dict) else ''
            if text:
                out.append({'ref': f'{run.job_id}:{run.profile_id}:{n}', 'text': text[:300],
                            'actor_id': run.job.actor_id})
    return out[:12]


def _suggestion(ticket, ref) -> Optional[dict]:
    for s in analysis_suggestions(ticket):
        if s['ref'] == ref:
            return s
    return None


# --- payloads ----------------------------------------------------------------

def handoff_context(ticket) -> dict:
    """The redacted ticket context a handoff sends — the evidence document
    "Analyze ticket" previews, built by the same code."""
    e = ev.build_evidence(ticket)
    return {'schema': e['schema'], 'ticket': e['ticket'], 'items': e['items'], 'excluded': e['excluded'],
            'redactions': e['redactions']}


def _absolute(request, name):
    path = reverse(name)
    return request.build_absolute_uri(path) if request is not None else path


def _base_payload(req, ticket, target, user, request):
    return {
        'contract': processor.CONTRACT,
        'request_id': str(req.id),
        'idempotency_key': req.idempotency_key,
        'organization_id': ticket.organization_id,
        'tenant_id': target.tenant_id,
        'ticket': {'id': ticket.pk, 'ref': ticket.ticket_number, 'revision': ev.ticket_revision(ticket)},
        'actor': {'id': user.pk, 'username': user.get_username()},
        'device': {'external_id': target.device.external_id, 'name': target.device.device_name},
        'events_url': _absolute(request, 'integration_api:events'),
    }


def _key_ok(key):
    return 8 <= len(key or '') <= 64 and key.replace('-', '').isalnum()


# --- create + send -----------------------------------------------------------

ROUTES = {'handoff': '/handoffs', 'diagnostic': '/diagnostics/requests', 'fix_referral': '/fixes'}


def _create_and_send(*, kind, ticket, target, user, key, digest_parts, fill, request, audit_text, extra=None):
    """Idempotent: the same key and the same request returns the first one;
    the same key for something else is refused (409)."""
    from audit.models import AuditLog
    from psa_ai.models import RMMRequest
    if not _key_ok(key):
        raise ActionRefused('Missing or malformed request key; start again.', 400)
    payload_digest = ev.digest(dict(digest_parts, kind=kind, ticket=ticket.pk, device=target.device.pk,
                                    connection=target.connection.pk))
    existing = RMMRequest.objects.filter(actor=user, idempotency_key=key).first()
    if existing is not None:
        if existing.payload_digest != payload_digest:
            raise ActionRefused('That request key was already used for something else.', 409)
        return existing, True
    try:
        with transaction.atomic():
            req = RMMRequest.objects.create(
                organization=ticket.organization, ticket=ticket, connection=target.connection,
                device=target.device, device_external_id=target.device.external_id,
                device_name=target.device.device_name[:255], tenant_id=target.tenant_id, actor=user, kind=kind,
                payload_digest=payload_digest, idempotency_key=key, **(extra or {}))
            payload = _base_payload(req, ticket, target, user, request)
            payload.update(fill)
            req.payload = payload
            req.save(update_fields=['payload'])
    except IntegrityError:
        req = RMMRequest.objects.get(actor=user, idempotency_key=key)
        if req.payload_digest != payload_digest:
            raise ActionRefused('That request key was already used for something else.', 409)
        return req, True
    AuditLog.log(user=user, action='create', organization=ticket.organization, object_type='psa_ai.RMMRequest',
                 object_repr=f'{req.get_kind_display()} on {ticket.ticket_number}'[:255],
                 description=f'{audit_text} on {ticket.ticket_number} to {target.connection.name} '
                             f'({target.device.device_name})'[:1000],
                 path=request.path if request is not None else '',
                 extra_data={'request': str(req.id), 'kind': kind, 'device': target.device.pk,
                             'connection': target.connection.pk, 'tenant': target.tenant_id})
    send(req)
    req.refresh_from_db()
    return req, False


def send(req):
    """POST the stored payload. A 2xx means accepted for processing, not
    received: a handoff shows Sent only after the signed receipt event."""
    from psa_ai.models import RMMRequest
    if req.connection.provider_type == 'rem0te':
        from integrations.rem0te import actions as rem0te_actions
        return rem0te_actions.send(req)
    try:
        data = processor._request(req.connection, 'POST', ROUTES[req.kind], req.payload,
                                  idempotency_key=req.idempotency_key)
    except processor.ProcessorConflict as e:
        RMMRequest.objects.filter(pk=req.pk).update(status='failed', error=str(e)[:500])
        return 'failed'
    except processor.ProcessorUnavailable as e:
        RMMRequest.objects.filter(pk=req.pk).update(status='unavailable', error=str(e)[:500])
        return 'unavailable'
    RMMRequest.objects.filter(pk=req.pk, status='created').update(
        status='pending', remote_id=str(data.get('remote_id') or data.get('id') or '')[:100])
    return 'pending'


def handoff(user, ticket, device_pk, key, context_digest, note='', request=None):
    target = find_target(ticket, device_pk)
    _usable_or_refuse(user, ticket, target, 'handoff', request)
    context = handoff_context(ticket)
    digest = ev.digest(context)
    if context_digest != digest:
        raise ActionRefused('The ticket changed since you previewed it. Preview again before sending.', 409)
    note = ev.redact((note or '').strip(), max_chars=MAX_NOTE_CHARS)
    authorize(user, ticket, target, 'handoff', request, digest=ev.digest({'context': digest, 'note': note}))
    return _create_and_send(kind='handoff', ticket=ticket, target=target, user=user, key=key,
                            digest_parts={'context': digest, 'note': note},
                            fill={'kind': 'handoff', 'context': context, 'context_digest': digest, 'note': note},
                            request=request, audit_text='RMM handoff sent')


def diagnostic(user, ticket, device_pk, diagnostic_key, key, request=None):
    target = find_target(ticket, device_pk)
    _usable_or_refuse(user, ticket, target, 'diagnostic', request)
    diag = next((d for d in diagnostics_for(target) if d['key'] == diagnostic_key), None)
    if diag is None:
        raise ActionRefused(f"{target.connection.name} doesn't offer that diagnostic for this device.", 400)
    authorize(user, ticket, target, 'diagnostic', request, digest=ev.digest({'diagnostic': diag['key']}))
    return _create_and_send(kind='diagnostic', ticket=ticket, target=target, user=user, key=key,
                            digest_parts={'diagnostic': diag['key']},
                            fill={'kind': 'diagnostic', 'diagnostic': diag['key'], 'readonly': True,
                                  'max_result_bytes': MAX_RESULT_BYTES},
                            request=request, audit_text=f'Read-only diagnostic "{diag["label"]}" requested',
                            extra={'diagnostic_key': diag['key'], 'diagnostic_label': diag['label'][:100]})


def refer_fix(user, ticket, device_pk, key, risk='low', title='', description='', suggestion_ref='',
              request=None, action_key=''):
    from rmm_permissions import can
    target = find_target(ticket, device_pk)
    rem0te_action = None
    if target.connection.provider_type == 'rem0te':
        # Rem0te takes catalog actions only; the risk is the action's own.
        rem0te_action = next((a for a in _catalog(target) if a['key'] == action_key), None)
        if rem0te_action is None:
            raise ActionRefused(f'Choose one of the actions {target.connection.name} offers.', 400)
        risk = rem0te_action.get('risk', 'high')
        title = title or rem0te_action['label']
    risk = 'high' if risk == 'high' else 'low'
    _usable_or_refuse(user, ticket, target, 'fix_high' if risk == 'high' else 'fix_low', request)
    source = {'type': 'technician'}
    if suggestion_ref:
        s = _suggestion(ticket, suggestion_ref)
        if s is None:
            raise ActionRefused('That analysis suggestion is no longer on this ticket.', 400)
        if s['actor_id'] != user.pk and not can(user, ticket.organization, 'remediation.refer',
                                                ticket=ticket).allowed:
            raise ActionRefused("Referring another technician's proposed fix needs “Refer a fix for independent "
                                'approval”.')
        job_id, profile_id, n = suggestion_ref.split(':')
        source = {'type': 'analysis', 'job_id': job_id, 'profile_id': int(profile_id), 'index': int(n)}
        description = description or s['text']
        title = title or s['text'][:120]
    title = ev.redact((title or '').strip(), max_chars=200)
    description = ev.redact((description or '').strip(), max_chars=MAX_FIX_CHARS)
    if not title or not description:
        raise ActionRefused('Give the fix a title and a description.', 400)
    fill = {'kind': 'fix_referral', 'fix': {'title': title, 'description': description, 'risk': risk,
                                            'source': source}}
    digest_parts = {'title': title, 'description': description, 'risk': risk, 'source': source}
    if rem0te_action is not None:
        from integrations.rem0te import actions as rem0te_actions, schema as rem0te_schema
        if not _key_ok(key):
            raise ActionRefused('Missing or malformed request key; start again.', 400)
        reason = f'Ticket {ticket.ticket_number}: {description}'
        try:
            fill['rem0te_proposal'] = rem0te_actions.proposal_body(
                connection=target.connection, user=user, ticket=ticket,
                device_external_id=target.device.external_id, action_key=rem0te_action['key'], reason=reason,
                origin='ai_suggestion' if suggestion_ref else 'technician', key=key)
        except rem0te_schema.SchemaError as e:
            raise ActionRefused(f'This device cannot take a Rem0te action proposal: {e}', 400)
        digest_parts['action'] = rem0te_action['key']
    decision = authorize(user, ticket, target, 'fix_high' if risk == 'high' else 'fix_low', request,
                         digest=ev.digest(digest_parts))
    req, replay = _create_and_send(kind='fix_referral', ticket=ticket, target=target, user=user, key=key,
                                   digest_parts=digest_parts, fill=fill,
                                   request=request, audit_text=f'Fix referred for independent approval ({risk} risk)',
                                   extra={'fix_title': title[:200], 'fix_risk': risk})
    if not replay and rem0te_action is not None and req.status == 'rejected':
        # Rem0te refused what ClientSt0r allowed: its refusal wins, on record.
        from rmm_permissions import record_remote_refusal
        record_remote_refusal(decision, user, ticket.organization, code=req.remote_status, message=req.error,
                              request=request)
    return req, replay


# --- remote launch -----------------------------------------------------------

def launch(user, ticket, device_pk, mode, request=None) -> str:
    """A validated, short-lived launch URL from the RMM. Never stored."""
    from audit.models import AuditLog
    from integrations.providers.rmm.console import host_of, validated_console_url
    from integrations.ticket_rmm import launch_hosts
    action = 'remote_control' if mode == 'control' else 'remote_view'
    target = find_target(ticket, device_pk)
    grant = _usable_or_refuse(user, ticket, target, action, request)
    authorize(user, ticket, target, action, request, digest=ev.digest({'mode': action, 'ticket': ticket.pk}))
    launch_id = str(uuid.uuid4())
    payload = {'contract': processor.CONTRACT, 'request_id': launch_id,
               'mode': 'control' if action == 'remote_control' else 'view', 'grant': grant,
               'organization_id': ticket.organization_id, 'tenant_id': target.tenant_id,
               'ticket': {'id': ticket.pk, 'ref': ticket.ticket_number},
               'actor': {'id': user.pk, 'username': user.get_username()},
               'device': {'external_id': target.device.external_id}}
    base = dict(user=user, action='api_call', organization=ticket.organization, object_type='psa_ai.RemoteLaunch',
                object_repr=f'Remote {payload["mode"]} on {ticket.ticket_number}'[:255],
                path=request.path if request is not None else '')
    extra = {'launch': launch_id, 'mode': payload['mode'], 'grant': grant, 'device': target.device.pk,
             'connection': target.connection.pk, 'tenant': target.tenant_id}
    try:
        data = processor._request(target.connection, 'POST', '/remote/launch', payload, idempotency_key=launch_id)
    except (processor.ProcessorUnavailable, processor.ProcessorConflict) as e:
        AuditLog.log(description=f'Remote {payload["mode"]} launch failed: {e}'[:1000], success=False,
                     extra_data=extra, **base)
        raise ActionRefused(f'{target.connection.name} could not start a session: {e}', 502)
    url = validated_console_url(str(data.get('url') or ''), launch_hosts(target.connection))
    expires = parse_datetime(str(data.get('expires_at') or ''))
    now = timezone.now()
    bad = ''
    if not url:
        bad = 'the launch address is not an https address on one of this connection\'s console hosts'
    elif expires is None or expires <= now or expires > now + LAUNCH_MAX_LIFETIME:
        bad = 'the launch address has no valid short expiry'
    if bad:
        AuditLog.log(description=f'Remote {payload["mode"]} launch refused: {bad} '
                                 f'(host {host_of(str(data.get("url") or ""))[:100] or "none"})'[:1000],
                     success=False, extra_data=extra, **base)
        raise ActionRefused(f'Refused the session from {target.connection.name}: {bad}.', 502)
    AuditLog.log(description=f'Remote {payload["mode"]} session launched on {target.device.device_name} '
                             f'through {target.connection.name} ({ticket.ticket_number})'[:1000],
                 extra_data=dict(extra, host=host_of(url)), **base)
    return url


# --- events from the RMM -----------------------------------------------------

def clean_text(value, max_chars) -> str:
    text = _ANSI.sub('', str(value or ''))
    return ev.redact(text, max_chars=max_chars)


def _clean_result(result) -> Tuple[str, int, bool]:
    if not isinstance(result, dict):
        return '', 0, False
    raw = str(result.get('text') or '')
    size = len(raw.encode('utf-8'))
    truncated = bool(result.get('truncated')) or size > MAX_RESULT_BYTES
    if size > MAX_RESULT_BYTES:
        raw = raw.encode('utf-8')[:MAX_RESULT_BYTES].decode('utf-8', 'ignore')
    text = clean_text(raw, MAX_RESULT_BYTES)
    return text, min(size, 10 ** 9), truncated


def apply_event(req, event_type, sequence, data) -> bool:
    """Move a request from a signed event. Only the request row changes —
    never the ticket, its comments or its status."""
    from psa_ai.models import RMMRequest
    rule = TRANSITIONS.get((req.kind, event_type))
    if rule is None:
        return False
    new_status, from_states = rule
    fields = {'status': new_status, 'last_event_sequence': sequence,
              'status_note': clean_text(data.get('message'), 300)}
    if new_status == 'sent':
        fields['confirmed_at'] = timezone.now()
    if event_type == 'diagnostic.completed':
        text, size, truncated = _clean_result(data.get('result'))
        fields.update(result_text=text, result_bytes=size, result_truncated=truncated)
    if new_status in ('failed', 'rejected'):
        fields['error'] = clean_text(data.get('message') or data.get('error'), 500)
    moved = RMMRequest.objects.filter(pk=req.pk, last_event_sequence__lt=sequence,
                                      status__in=from_states).update(**fields)
    if moved and event_type == 'diagnostic.completed' and fields.get('result_bytes'):
        from tech_access import detection
        try:
            detection.record(req.actor, 'diagnostic_bytes', str(req.pk), req.organization_id, channel='api',
                             amount=fields['result_bytes'])
        except Exception:
            pass
    return bool(moved)


def expire_stale(now=None) -> int:
    from psa_ai.models import RMMRequest
    now = now or timezone.now()
    n = 0
    for kind, age in EXPIRE_AFTER.items():
        # Work the RMM approved or is running is its to finish; only requests
        # still waiting for an answer expire.
        waiting = ['created', 'pending', 'received'] + (['running'] if kind != 'fix_referral' else [])
        n += (RMMRequest.objects.filter(kind=kind, created_at__lt=now - age, status__in=waiting)
              .update(status='expired', error='No answer from the RMM in time.'))
    return n
