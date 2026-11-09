"""
ClientSt0r's side of the rem0te job API (docs/contracts/ticket-rmm-v1).

  GET  {rem0te}/api/integration/v1/capabilities     what this rem0te supports
  POST {rem0te}/api/integration/v1/jobs              submit an analysis job
  GET  {rem0te}/api/integration/v1/jobs/{job_id}     poll a job's state

Every request is signed (integration_auth.py) and carries the job's
idempotency key, so resubmitting the same job returns rem0te's original
job and a changed payload under the same key is refused with 409.

rem0te is sent the binding, not the ticket: IDs, revision, evidence
digest, profile names and locations, the delegated identity and where to
call back. Ticket text stays here; the gateway builds the prompt from the
stored evidence when rem0te asks for a model run.

An unreachable rem0te marks the job "unavailable". Nothing else about the
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
    from integrations.providers.rmm.rem0te import integration_settings
    base = configured_service_policy()
    if integration_settings(conn)['location'] == 'local':
        return OutboundPolicy(allow_lan=True, allow_local=base.allow_local, allowed_ports=None)
    return base


def _request(conn, method, path, payload=None, idempotency_key=''):
    from integrations.providers.rmm.rem0te import integration_secrets, integration_settings
    settings_ = integration_settings(conn)
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
        r = session.request(method, settings_['site'] + full, data=body or None, headers=headers,
                            timeout=TIMEOUT, allow_redirects=False)
    except (requests.RequestException, BlockedDestinationError) as e:
        raise ProcessorUnavailable(f'rem0te could not be reached ({e.__class__.__name__}).')
    if r.status_code == 409:
        raise ProcessorConflict('rem0te already has a different job under this idempotency key.')
    if r.status_code >= 300:
        raise ProcessorUnavailable(f'rem0te answered HTTP {r.status_code}.')
    try:
        return r.json()
    except ValueError:
        raise ProcessorUnavailable('rem0te returned something other than JSON.')


def refresh_capabilities(conn):
    from integrations.providers.rmm.rem0te import record_capabilities
    doc = _request(conn, 'GET', '/capabilities')
    if doc.get('contract') != CONTRACT:
        raise ProcessorUnavailable(f'rem0te does not speak {CONTRACT}.')
    record_capabilities(conn, doc)
    return doc


def job_payload(job, request=None):
    from integrations.providers.rmm.rem0te import integration_settings

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
    """Send the job to rem0te. Sets status submitted / unavailable / failed."""
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
        job.runs.filter(status='pending').update(status='refused', error='rem0te was unavailable.',
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
        note = {'job.completed': 'rem0te finished without asking for this model.',
                'job.failed': 'rem0te reported the job failed.',
                'job.cancelled': 'rem0te cancelled the job.'}[event_type]
        job.runs.filter(status='pending').update(status='refused', error=note, finished_at=timezone.now())
        gateway.finish_job(job)
    return True


def poll(job, force=False):
    """Recover missed callbacks by asking rem0te for the job's state."""
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
