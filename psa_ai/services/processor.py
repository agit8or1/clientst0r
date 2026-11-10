"""
ClientSt0r's side of the paired RMM's job API (docs/contracts/ticket-rmm-v1).
Any RMM that implements the contract can be the processor; rem0te is the
reference implementation.

  GET  {rmm}/api/integration/v1/capabilities     what this RMM supports, and its tenant
  POST {rmm}/api/integration/v1/jobs              submit an analysis job
  GET  {rmm}/api/integration/v1/jobs/{job_id}     poll a job's state

Handoffs, diagnostics, remote launch and fix referrals live in
services/rmm_actions.py and use the same signed `_request`.

Every request is signed (integration_auth.py) and carries the job's
idempotency key, so resubmitting the same job returns the RMM's original
job and a changed payload under the same key is refused with 409.

The RMM is sent the binding, not the ticket: IDs, revision, evidence
digest, profile names and locations, the delegated identity and where to
call back. Ticket text stays here; the gateway builds the prompt from the
stored evidence when the RMM asks for a model run.

An unreachable RMM marks the job "unavailable". Nothing else about the
ticket changes, and manual work carries on.
"""
from __future__ import annotations

import json
import logging

import requests
from django.urls import reverse
from django.utils import timezone

from core.safe_http import BlockedDestinationError, OutboundPolicy, configured_service_policy, guard_session

from . import gateway, integration_auth

logger = logging.getLogger('psa_ai')

CONTRACT = 'ticket-rmm-v1'
API = '/api/integration/v1'
TIMEOUT = (5, 15)
POLL_MIN_SECONDS = 15


class ProcessorUnavailable(Exception):
    pass


class ProcessorConflict(Exception):
    pass


def _policy(conn):
    from integrations.ticket_rmm import settings as integration_settings
    base = configured_service_policy()
    if integration_settings(conn)['location'] == 'local':
        return OutboundPolicy(allow_lan=True, allow_local=base.allow_local, allowed_ports=None)
    return base


MAX_RESPONSE = 256 * 1024


def _request(conn, method, path, payload=None, idempotency_key=''):
    from integrations.ticket_rmm import secrets as integration_secrets, settings as integration_settings
    settings_ = integration_settings(conn)
    site = settings_['site']
    if not (site.startswith('https://') or (site.startswith('http://') and settings_['location'] == 'local')):
        raise ProcessorUnavailable('The RMM address must use https (plain http only for an on-premises pairing).')
    body = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode() if payload is not None else b''
    full = API + path
    headers = integration_auth.sign(integration_secrets(conn)['outbound'], method, full, body, settings_['key_id'])
    headers['Content-Type'] = 'application/json'
    headers['Accept'] = 'application/json'
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key
    session = requests.Session()
    session.trust_env = False
    guard_session(session, _policy(conn))
    try:
        r = session.request(method, site + full, data=body or None, headers=headers,
                            timeout=TIMEOUT, allow_redirects=False)
    except (requests.RequestException, BlockedDestinationError) as e:
        raise ProcessorUnavailable(f'The RMM could not be reached ({e.__class__.__name__}).')
    if r.status_code == 409:
        raise ProcessorConflict('The RMM already has a different request under this idempotency key.')
    if r.status_code >= 300:
        raise ProcessorUnavailable(f'The RMM answered HTTP {r.status_code}{_error_code(r)}.')
    if len(r.content or b'') > MAX_RESPONSE:
        raise ProcessorUnavailable('The RMM answered with more data than the contract allows.')
    try:
        data = r.json()
    except ValueError:
        raise ProcessorUnavailable('The RMM returned something other than JSON.')
    if not isinstance(data, dict):
        raise ProcessorUnavailable('The RMM returned something other than a JSON object.')
    return data


def _error_code(r):
    try:
        body = r.json()
    except ValueError:
        return ''
    code = str(body.get('error') or '') if isinstance(body, dict) else ''
    return f' ({code[:60]})' if code and code.replace('_', '').isalnum() else ''


def refresh_capabilities(conn):
    """Ask the RMM what it supports and which tenant it answers for, and
    record the answer (integrations/ticket_rmm.py pins the tenant on the
    first success). Returns the stored check; failures are recorded on the
    connection, not raised."""
    from integrations.ticket_rmm import record_capabilities, record_failure, settings
    if not settings(conn)['enabled']:
        record_failure(conn, 'The pairing is not switched on and approved yet.')
        return {'ok': False, 'error': 'not enabled'}
    try:
        doc = _request(conn, 'GET', '/capabilities')
    except (ProcessorUnavailable, ProcessorConflict) as e:
        record_failure(conn, str(e))
        return {'ok': False, 'error': str(e)}
    if doc.get('contract') != CONTRACT:
        record_failure(conn, f'The RMM does not implement {CONTRACT}.')
        return {'ok': False, 'error': 'contract'}
    return record_capabilities(conn, doc)


def job_payload(job, request=None):
    from integrations.ticket_rmm import settings as integration_settings

    def absolute(name, **kw):
        path = reverse(name, kwargs=kw)
        return request.build_absolute_uri(path) if request is not None else path
    return {
        'contract': CONTRACT,
        'job_id': str(job.id),
        'kind': job.kind,
        'correlation_id': str(job.correlation_id),
        'idempotency_key': job.idempotency_key,
        'organization_id': job.organization_id,
        'business_id': job.business_id,
        'ticket': {'id': job.ticket_id, 'ref': job.ticket.ticket_number, 'revision': job.ticket_revision},
        'actor': {'id': job.actor_id, 'delegation': gateway.delegation_token(job)},
        'endpoint': None,
        'profiles': [{'id': r.profile_id, 'name': r.profile.name, 'provider': r.profile.provider,
                      'location': r.profile.location} for r in job.runs.select_related('profile')],
        'evidence_digest': job.evidence_digest,
        'processing_location': integration_settings(job.connection)['location'],
        'expires_at': job.expires_at.isoformat(),
        'inference_url': absolute('integration_api:inference'),
        'events_url': absolute('integration_api:events'),
    }


def submit(job, request=None):
    """Send the job to the paired RMM. Sets status submitted / unavailable / failed."""
    from psa_ai.models import AnalysisJob
    payload = job_payload(job, request)
    try:
        data = _request(job.connection, 'POST', '/jobs', payload, idempotency_key=job.idempotency_key)
    except ProcessorConflict as e:
        AnalysisJob.objects.filter(pk=job.pk).update(status='failed', error=str(e))
        gateway._expire(job)
        return 'failed'
    except ProcessorUnavailable as e:
        AnalysisJob.objects.filter(pk=job.pk).update(status='unavailable', error=str(e))
        job.runs.filter(status='pending').update(status='refused', error='The RMM was unavailable.',
                                                 finished_at=timezone.now())
        return 'unavailable'
    AnalysisJob.objects.filter(pk=job.pk, status='created').update(
        status='submitted', processor_job_id=str(data.get('processor_job_id') or data.get('job_id') or '')[:100])
    return 'submitted'


EVENT_TYPES = {'job.accepted', 'job.running', 'job.completed', 'job.failed', 'job.cancelled'}


def apply_event(job, event_type, sequence):
    """Advance a job from a processor event or poll. Events only move the
    job's own status: none can approve a fix, post a reply, or touch the
    ticket."""
    from psa_ai.models import AnalysisJob
    if event_type not in EVENT_TYPES or job.is_terminal:
        return False
    if sequence is not None:
        moved = AnalysisJob.objects.filter(pk=job.pk, last_event_sequence__lt=sequence).update(
            last_event_sequence=sequence)
        if not moved:
            return False  # duplicate or out of order
    if event_type == 'job.accepted':
        AnalysisJob.objects.filter(pk=job.pk, status='created').update(status='submitted')
    elif event_type == 'job.running':
        AnalysisJob.objects.filter(pk=job.pk, status__in=['created', 'submitted']).update(status='running')
    else:
        note = {'job.completed': 'The RMM finished without asking for this model.',
                'job.failed': 'The RMM reported the job failed.',
                'job.cancelled': 'The RMM cancelled the job.'}[event_type]
        job.runs.filter(status='pending').update(status='refused', error=note, finished_at=timezone.now())
        gateway.finish_job(job)
    return True


def poll(job, force=False):
    """Recover missed callbacks by asking the RMM for the job's state."""
    from psa_ai.models import AnalysisJob
    if job.is_terminal:
        return job
    if job.expires_at <= timezone.now():
        gateway._expire(job)
        job.refresh_from_db()
        return job
    if not force and job.last_polled_at and (timezone.now() - job.last_polled_at).total_seconds() < POLL_MIN_SECONDS:
        return job
    AnalysisJob.objects.filter(pk=job.pk).update(last_polled_at=timezone.now())
    try:
        data = _request(job.connection, 'GET', f'/jobs/{job.id}')
    except (ProcessorUnavailable, ProcessorConflict):
        return job
    state = str(data.get('status') or '')
    mapping = {'accepted': 'job.accepted', 'queued': 'job.accepted', 'running': 'job.running',
               'completed': 'job.completed', 'failed': 'job.failed', 'cancelled': 'job.cancelled'}
    if state in mapping:
        seq = data.get('sequence')
        apply_event(job, mapping[state], int(seq) if isinstance(seq, int) else None)
    job.refresh_from_db()
    return job
