"""
Rem0te action proposals from a ticket (contract ticket-rmm-v1,
POST /action-proposals, GET /action-proposals/{job_id}).

A proposal authorizes nothing. ClientSt0r proposes one of the catalog
actions Rem0te advertised in its capabilities (`features.actions`, e.g.
`windows.service.start@1`) with fixed parameters from ClientSt0r's own table
(`pairing.KNOWN_ACTIONS`) — there is no field for a command, script, path or
URL. Rem0te checks the delegated technician's live access to the computer,
answers `awaiting_approval` with an `approval_url`, and approval happens
there, by passkey, by Rem0te's approvers. ClientSt0r shows the link and
Rem0te's status; it never marks anything approved and nothing here can close
the ticket or reply to the customer.

The proposal is stored on the RMMRequest (kind fix_referral) exactly as sent,
so a retry after a restart sends the same bytes under the same
idempotency key: Rem0te answers 200 with the original proposal.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from . import client, pairing, protocol, schema

logger = logging.getLogger('integrations.rem0te')

POLL_EVERY = timedelta(seconds=30)

# Rem0te's proposal status → RMMRequest.status.
STATUS_MAP = {
    'awaiting_approval': 'received',
    'approved': 'approved',
    'dispatched': 'running',
    'succeeded': 'succeeded',
    'failed': 'failed',
    'refused_by_endpoint': 'failed',
    'not_executed': 'failed',
    'unknown': 'failed',
    'rejected': 'rejected',
    'canceled': 'rejected',
    'expired': 'expired',
}
OPEN_REMOTE = {'awaiting_approval', 'approved', 'dispatched'}

REFUSAL_TEXT = {
    'ACTION_NOT_IN_CATALOG': 'Rem0te does not offer that action.',
    'PARAMS_NOT_ALLOWED': 'Rem0te refused the action\'s parameters.',
    'ACTION_NOT_GRANTED': 'Your Rem0te account may not request that action on this computer.',
    'PROTECTED_DEVICE_CLASS': 'Rem0te protects this kind of computer from that action.',
    'ENDPOINT_NOT_READY': 'The computer is not ready for actions in Rem0te (offline, or its agent is too old).',
    'ACTION_PENDING': 'Rem0te already has an open action on this computer.',
    'ACTION_UNRECONCILED': 'An earlier action on this computer has not been reconciled in Rem0te.',
    'APPROVAL_SIGNER_ERROR': 'Rem0te\'s approval signer is unavailable; try again later.',
    'APPROVAL_SIGNER_REFUSED': 'Rem0te\'s approval signer refused the plan.',
    'FORBIDDEN': 'Rem0te refused the technician or organization. Check the mappings in Rem0te.',
    'DELEGATION_INVALID': 'Rem0te refused the technician delegation. Check the delegation key and clocks.',
    'IDEMPOTENCY_CONFLICT': 'Rem0te already has a different proposal under this request key.',
}


def proposal_body(*, connection, user, ticket, device_external_id, action_key, reason, origin, key) -> dict:
    """The canonical proposal, every default explicit (req_sha256 covers the
    body after defaults)."""
    from .jobs import ticket_ext_id
    action = pairing.KNOWN_ACTIONS[action_key]
    body = {
        'contract': protocol.CONTRACT,
        'idempotency_key': f'cs-{user.pk}-{key}'[:128],
        'organization_id': pairing.organization_id(connection),
        'technician_id': pairing.technician_id(user),
        'rem0te_endpoint_id': device_external_id,
        'action': {'id': action['id'], 'version': action['version']},
        'params': dict(action['params']),
        'reason': reason[:500],
        'origin': origin,
        'ticket_ref': ticket_ext_id(ticket),
        'starts_in_minutes': 0,
        'window_hours': 4,
    }
    schema.validate('action-proposal-request', body)
    return body


def _update(req, **fields):
    from psa_ai.models import RMMRequest
    RMMRequest.objects.filter(pk=req.pk).update(**fields, updated_at=timezone.now())
    for k, v in fields.items():
        setattr(req, k, v)


def _apply_proposal(req, data) -> bool:
    if schema.errors('action-proposal', data) or data.get('idempotency_key') != req.payload['rem0te_proposal'][
            'idempotency_key'] or data.get('rem0te_endpoint_id') != req.device_external_id:
        _update(req, error='Rem0te answered with a proposal that does not match what was sent.')
        return False
    approval = str(data.get('approval_url') or '')
    note = client.safe_text(data.get('status_reason') or '', 300)
    observed = data.get('observed')
    if isinstance(observed, dict):
        note = (note + ' ' if note else '') + 'Observed: ' + ', '.join(
            f'{client.safe_text(k, 20)}={client.safe_text(v, 30)}' for k, v in list(observed.items())[:6])
    _update(req, remote_id=str(data['job_id'])[:100], remote_status=data['status'][:40],
            status=STATUS_MAP.get(data['status'], 'failed'), status_note=note[:500], error='',
            approval_url=approval[:500] if approval.startswith('https://') else '',
            confirmed_at=req.confirmed_at or timezone.now())
    return True


def send(req) -> str:
    body = req.payload.get('rem0te_proposal')
    if not body:
        _update(req, status='failed', error='No Rem0te proposal stored on this request.')
        return 'failed'
    try:
        r = client.request(req.connection, 'POST', '/action-proposals', body,
                           delegation=('actions:propose', body['technician_id'],
                                       protocol.sha256_hex(protocol.canonical_json(body))))
    except (client.NotSent, protocol.ProtocolError) as e:
        _update(req, status='unavailable', error=f'Not sent to Rem0te: {getattr(e, "message", e)}'[:500])
        return 'unavailable'
    if r.ok:
        return 'pending' if _apply_proposal(req, r.data if isinstance(r.data, dict) else {}) else 'pending'
    if r.transport in ('unreachable', 'timeout', 'read') or r.status >= 500 or r.status == 429:
        # Kept 'created': the poller re-sends the same proposal, and Rem0te's
        # idempotency answers with the original if the first one landed.
        _update(req, error=f'{r.message} ClientSt0r will retry.'[:500])
        return 'retrying'
    text = REFUSAL_TEXT.get(r.code, 'Rem0te refused the proposal.')
    _update(req, status='rejected' if r.status in (400, 403, 409) else 'failed', remote_status=r.code[:40],
            error=f'{text} ({r.code}: {r.message})'[:500])
    return 'failed'


def refresh(req, force=False) -> str:
    """Re-send an unsent proposal, or read Rem0te's status for a sent one."""
    if req.status in ('created',) and not req.remote_id:
        return send(req)
    if req.remote_status not in OPEN_REMOTE or not req.remote_id:
        return req.status
    if not force and req.updated_at and timezone.now() - req.updated_at < POLL_EVERY:
        return req.status
    try:
        r = client.request(req.connection, 'GET', f'/action-proposals/{req.remote_id}',
                           delegation=('actions:read', pairing.technician_id(req.actor), None))
    except (client.NotSent, protocol.ProtocolError) as e:
        _update(req, error=str(getattr(e, 'message', e))[:500])
        return req.status
    if r.ok and isinstance(r.data, dict):
        _apply_proposal(req, r.data)
    else:
        _update(req, error=f'Could not read the proposal from Rem0te ({r.code}: {r.message})'[:500])
    return req.status


def poll_open(limit=100) -> int:
    from psa_ai.models import RMMRequest
    n = 0
    qs = (RMMRequest.objects.filter(connection__provider_type='rem0te', kind=RMMRequest.KIND_FIX)
          .exclude(status__in=['succeeded', 'failed', 'rejected', 'expired', 'unavailable', 'completed', 'sent'])
          .select_related('connection', 'actor').order_by('updated_at')[:limit])
    for req in qs:
        try:
            refresh(req)
            n += 1
        except Exception:
            logger.exception('refreshing Rem0te proposal %s failed', req.pk)
    return n
