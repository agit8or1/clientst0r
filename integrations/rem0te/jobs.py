"""
Ticket analysis through Rem0te (contract ticket-rmm-v1, Ed25519).

  submit   POST {rem0te}/api/integration/v1/jobs      delegation ticket_analysis:submit
  poll     GET  {rem0te}/api/integration/v1/jobs/{id}/events?after=n   (scope ticket_analysis:read)
  events   POST {clientst0r}/api/integration/v1/events        {event, signature}
  infer    POST {clientst0r}/api/integration/v1/inference     one model run, signed response

What Rem0te gets: the ticket's redacted evidence (the same document the
technician previewed), the ids Rem0te maps, model *profile names* and,
when the ticket's asset is verifiably one of Rem0te's computers, that
computer's immutable Rem0te id. Never a provider key, a model name ahead of
time, a hostname or anything from the vault.

Idempotency. The job request is built once, stored (AnalysisJob
.processor_request) and re-sent byte-for-byte on every retry with a fresh
signature, nonce and delegation `jti`. Rem0te answers a replay with the
original job, so a retry after a timeout, a restart or a lost response
can never create a second job; a lost response is also recovered from the
first signed event, which carries the job's correlation id and payload hash.

Model runs. Rem0te asks the inference gateway once per profile. A retry of
the same run (Rem0te retries transient failures, with a new request id) is
answered from the stored run: the model is called at most once per
(job, profile). The prompt is built from what ClientSt0r sent, plus the
Rem0te-observed endpoint segments only when the job named an endpoint.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import timezone as dt_timezone
from typing import Dict, List, Optional, Tuple

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import client, pairing, protocol, schema

logger = logging.getLogger('integrations.rem0te')

POLL_MIN_SECONDS = 15
MAX_PROFILES = 3
WAIT_FOR_WORKER_SECONDS = 25
TERMINAL_EVENTS = {'job.succeeded': 'completed', 'job.partial': 'partial', 'job.failed': 'failed',
                   'job.expired': 'expired'}
_CTRL = re.compile('[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]')
# Rem0te's clean(): what it strips from ticket text before building segments.
_REM0TE_CLEAN = re.compile('[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏‪-‮⁦-⁩]')


def iso(dt) -> str:
    """JavaScript's toISOString(): UTC, milliseconds, Z."""
    dt = dt.astimezone(dt_timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def _text(s, limit) -> str:
    return _CTRL.sub('', str(s or ''))[:limit]


def ticket_ext_id(ticket) -> str:
    ref = ticket.ticket_number or ''
    return ref if protocol.EXT_ID_RE.match(ref) else f'ticket-{ticket.pk}'


def ticket_revision_int(job) -> int:
    """The contract wants an integer revision; ClientSt0r's revision is a
    SHA-256. Its first 28 bits are stable for a revision and change with it."""
    return int((job.ticket_revision or '0')[:7] or '0', 16)


def endpoint_for(job) -> Optional[str]:
    """The Rem0te computer id for this ticket, only through a verified,
    same-customer association on this very connection (rmm_actions.targets)."""
    from psa_ai.services.rmm_actions import targets
    device = job.endpoint_device
    if device is None:
        for t in targets(job.ticket):
            if t.connection.pk == job.connection_id:
                device = t.device
                break
    if device is None or device.connection_id != job.connection_id:
        return None
    ext = str(device.external_id or '')
    return ext if re.match(r'^[a-z0-9]{1,64}$', ext) else None


def build_request(job) -> dict:
    """The job-request document, every default explicit, so its canonical
    hash is the one Rem0te computes after parsing (req_sha256)."""
    ev = job.evidence or {}
    items = ev.get('items') or []
    subject = next((i['text'] for i in items if i.get('kind') == 'ticket.subject'), '') or job.ticket.subject
    body = next((i['text'] for i in items if i.get('kind') == 'ticket.description'), '')
    created = iso(job.created_at or timezone.now())
    comments = []
    for i in items:
        kind = i.get('kind')
        if kind == 'comment':
            role = 'staff' if i.get('role') == 'technician' else ('system' if i.get('role') == 'system' else 'customer')
            at = i.get('at') or ''
            try:
                from django.utils.dateparse import parse_datetime
                at = iso(parse_datetime(at)) if at else created
            except (TypeError, ValueError, AttributeError):
                at = created
            comments.append({'id': str(i['id']), 'author_role': role, 'created_at': at,
                             'body': _text(i.get('text'), 8000)})
        elif kind in ('asset', 'rmm_status'):
            comments.append({'id': str(i['id']), 'author_role': 'system', 'created_at': created,
                             'body': _text(i.get('text'), 8000)})
    endpoint = endpoint_for(job)
    req = {
        'contract': protocol.CONTRACT,
        'idempotency_key': job.idempotency_key,
        'correlation_id': str(job.correlation_id),
        'organization_id': pairing.organization_id(job.connection),
        'technician_id': pairing.technician_id(job.actor),
        'ticket': {
            'id': ticket_ext_id(job.ticket),
            'revision': ticket_revision_int(job),
            'subject': _text(subject, 512),
            'body': _text(body, 20000),
            'comments': comments[:50],
            'attachments_text': [],
        },
        'endpoint': {'rem0te_endpoint_id': endpoint} if endpoint else None,
        'model_profiles': [pairing.profile_slug(r.profile) for r in job.runs.select_related('profile')][:MAX_PROFILES],
        'evidence': {'include_endpoint_inventory': bool(endpoint)},
        'expires_at': iso(job.expires_at),
    }
    schema.validate('job-request', req)
    return req


def request_sha256(req: dict) -> str:
    return protocol.sha256_hex(protocol.canonical_json(req))


def _set(job, **fields):
    from psa_ai.models import AnalysisJob
    AnalysisJob.objects.filter(pk=job.pk).update(**fields, updated_at=timezone.now())
    for k, v in fields.items():
        setattr(job, k, v)


def _refuse_pending(job, note):
    job.runs.filter(status='pending').update(status='refused', error=note[:500], finished_at=timezone.now())


def submit(job) -> str:
    """Send (or re-send) the job. Returns 'submitted', 'retrying' or 'failed'."""
    if not job.processor_request:
        try:
            req = build_request(job)
        except schema.SchemaError as e:
            _set(job, status='failed', processor_error_code='INVALID_REQUEST',
                 error=f'ClientSt0r could not build a valid Rem0te job request: {e}'[:1000])
            _refuse_pending(job, 'Not sent.')
            return 'failed'
        _set(job, processor_request=req)
    req = job.processor_request
    try:
        r = client.request(job.connection, 'POST', '/jobs', req,
                           delegation=('ticket_analysis:submit', req['technician_id'], request_sha256(req)))
    except (client.NotSent, protocol.ProtocolError) as e:
        _set(job, status='failed', processor_error_code=getattr(e, 'code', 'NOT_CONFIGURED_LOCAL'),
             error=f'Not sent to Rem0te: {getattr(e, "message", str(e))}'[:1000])
        _refuse_pending(job, 'Not sent.')
        return 'failed'
    if r.ok:
        data = r.data if isinstance(r.data, dict) else {}
        if schema.errors('job', data) or data.get('idempotency_key') != job.idempotency_key \
                or data.get('payload_sha256') != request_sha256(req):
            _set(job, processor_error_code='RESPONSE_INVALID',
                 error='Rem0te accepted the job but its answer does not match what was sent; '
                       'ClientSt0r will confirm it from Rem0te\'s signed events.')
            return 'retrying'
        _set(job, processor_job_id=data['job_id'], processor_error_code='', error='',
             status='submitted' if job.status == 'created' else job.status)
        from . import health
        health.clear(job.connection, 'jobs')
        if data['status'] in ('succeeded', 'partial', 'failed', 'expired'):
            poll(job, force=True)  # an idempotent replay of a finished job: fetch its signed events
        return 'submitted'
    from . import health
    if r.code == 'CONTAINED' or r.status == 423:
        # A containment pause in Rem0te: an administrator decision, not an
        # outage. The job ends now with the reason (Rem0te's free-text pause
        # reason is not kept: /capabilities deliberately never discloses it).
        why = ('Rem0te has paused ClientSt0r jobs for this business (containment). Nothing was queued; run the '
               'analysis again once a Rem0te administrator lifts the pause.')
        _set(job, status='failed', processor_error_code='CONTAINED', error=why)
        _refuse_pending(job, 'Rem0te has paused this business.')
        health.note(job.connection, 'jobs', why, code='CONTAINED',
                    action='A Rem0te administrator lifts the pause once the review is done.')
        return 'failed'
    retryable = r.transport in ('unreachable', 'timeout', 'read') or r.status >= 500 or r.status == 429
    if retryable:
        _set(job, processor_error_code=r.code[:64],
             error=f'{r.message} ClientSt0r keeps retrying (same request, nothing duplicated) until the job '
                   'expires.'[:1000])
        health.note(job.connection, 'jobs', f'Analysis jobs are waiting to be sent to Rem0te: {r.message}',
                    code=r.code, action='ClientSt0r retries every minute with the same request.')
        return 'retrying'
    reason = describe_refusal(r)
    _set(job, status='failed', processor_error_code=r.code[:64], error=reason[:1000])
    _refuse_pending(job, 'Rem0te refused the job.')
    if r.code == 'FORBIDDEN':
        health.note(job.connection, 'technician', f'Rem0te refused {req["technician_id"]}: {r.message}',
                    code='FORBIDDEN', action='Map the technician in Rem0te and grant integration:ticket_analysis.')
    else:
        health.note(job.connection, 'jobs', reason, code=r.code)
    return 'failed'


def describe_refusal(r: client.Result) -> str:
    hints = {
        'FORBIDDEN': 'Rem0te refused the technician or organization: {m} Check the organization and technician '
                     'mappings and the technician\'s "Ticket analysis (ClientSt0r)" capability in Rem0te.',
        'DELEGATION_INVALID': 'Rem0te refused the technician delegation: {m} Check the delegation key in the '
                              'peers file and the clocks.',
        'UNAUTHENTICATED': 'Rem0te refused ClientSt0r\'s signature: {m} Run Check pairing on the connection.',
        'REPLAYED': 'Rem0te refused a replayed token or nonce: {m}',
        'IDEMPOTENCY_CONFLICT': 'Rem0te already has a different job under this request key.',
        'INVALID_REQUEST': 'Rem0te refused the job request: {m}',
        'NOT_CONFIGURED': 'Rem0te has no integration configured (NOT_CONFIGURED).',
        'TOO_LARGE': 'The ticket is too large for Rem0te.',
    }
    text = hints.get(r.code, 'Rem0te refused the job ({c}): {m}')
    return text.format(m=r.message or f'HTTP {r.status}.', c=r.code or r.status)


def poll(job, force=False):
    """Recover missed callbacks: re-submit an unconfirmed job, or fetch the
    job's signed events after the last one applied."""
    from psa_ai.models import AnalysisJob
    if job.is_terminal:
        return job
    if job.expires_at <= timezone.now():
        _set(job, status='expired', error=job.error or 'The job expired before Rem0te finished it.')
        _refuse_pending(job, 'Job expired.')
        return job
    if not force and job.last_polled_at and (timezone.now() - job.last_polled_at).total_seconds() < POLL_MIN_SECONDS:
        return job
    _set(job, last_polled_at=timezone.now())
    if not job.processor_job_id:
        submit(job)
        job.refresh_from_db()
        return job
    try:
        r = client.request(job.connection, 'GET', f'/jobs/{job.processor_job_id}/events',
                           query={'after': job.last_event_sequence},
                           delegation=('ticket_analysis:read', pairing.technician_id(job.actor), None))
    except (client.NotSent, protocol.ProtocolError) as e:
        _set(job, processor_error_code='NOT_CONFIGURED_LOCAL', error=str(getattr(e, 'message', e))[:1000])
        return job
    if not r.ok:
        _set(job, processor_error_code=r.code[:64],
             error=(describe_refusal(r) if r.status in (401, 403, 404) else r.message)[:1000])
        return job
    for item in (r.data or {}).get('events') or []:
        if isinstance(item, dict):
            apply_signed_event(job.connection, item, via='poll')
    job.refresh_from_db()
    if not job.is_terminal and job.processor_error_code:
        _set(job, processor_error_code='', error='')
    return job


def apply_signed_event(connection, signed: dict, via='push') -> Tuple[int, str]:
    """Verify and apply one {event, signature}. Returns (HTTP status, outcome)."""
    from psa_ai.models import AnalysisJob, ProcessorEvent
    event, signature = signed.get('event'), signed.get('signature')
    errs = schema.errors('signed-event', signed)
    if errs:
        return 400, 'invalid: ' + '; '.join(errs[:3])
    problem = protocol.verify_event_signature(event, signature, pairing.keyring(connection))
    if problem:
        logger.warning('Rem0te job event refused for connection %s: %s', connection.pk, problem)
        from . import health
        health.note(connection, 'inbound_auth', f'A job event did not verify with Rem0te\'s signing key ({problem}).',
                    code='EVENT_SIGNATURE', action="Compare Rem0te's signing key on this connection with its "
                                                   'capabilities (Test connection).')
        return 401, problem
    from . import identity
    ident = identity.get(create=False)
    if event['peer_id'] != getattr(ident, 'peer_id', None) or event['organization_id'] != pairing.organization_id(connection):
        return 404, 'not for this peer or organization'
    jobs = AnalysisJob.objects.filter(connection=connection, protocol=AnalysisJob.PROTOCOL_REM0TE)
    job = jobs.filter(processor_job_id=event['job_id']).first()
    if job is None:
        # The submit response was lost: bind by correlation id, idempotency
        # key and payload hash, all three, from Rem0te's signed snapshot.
        try:
            corr = uuid.UUID(event['correlation_id'])
        except ValueError:
            corr = None
        cand = jobs.filter(correlation_id=corr, processor_job_id='').first() if corr else None
        if cand is not None and event['job'].get('idempotency_key') == cand.idempotency_key \
                and cand.processor_request and event['job'].get('payload_sha256') == request_sha256(cand.processor_request):
            AnalysisJob.objects.filter(pk=cand.pk, processor_job_id='').update(processor_job_id=event['job_id'])
            job = AnalysisJob.objects.get(pk=cand.pk)
    if job is None:
        return 404, 'job unknown'
    try:
        with transaction.atomic():
            row = ProcessorEvent.objects.create(job=job, event_id=event['event_id'], sequence=event['sequence'],
                                                event_type=event['type'])
    except IntegrityError:
        return 200, 'duplicate'
    applied = _apply(job, event)
    if applied:
        ProcessorEvent.objects.filter(pk=row.pk).update(applied=True)
    return 200, 'applied' if applied else 'recorded'


def _apply(job, event) -> bool:
    from psa_ai.models import AnalysisJob
    seq, etype, snap = event['sequence'], event['type'], event['job']
    with transaction.atomic():
        job = AnalysisJob.objects.select_for_update().get(pk=job.pk)
        if job.is_terminal or seq <= job.last_event_sequence:
            return False
        fields = {'last_event_sequence': seq}
        if etype == 'job.accepted' and job.status == 'created':
            fields['status'] = 'submitted'
        elif etype == 'job.running' and job.status in ('created', 'submitted'):
            fields['status'] = 'running'
        elif etype in TERMINAL_EVENTS:
            fields['status'] = TERMINAL_EVENTS[etype]
            fields['processor_result'] = snap.get('result') or {}
            err = snap.get('error') or {}
            if err:
                fields['processor_error_code'] = str(err.get('code') or '')[:64]
                fields['error'] = f'Rem0te: {err.get("code")} — {client.safe_text(err.get("message"), 300)}'[:1000]
            else:
                fields['processor_error_code'] = ''
                fields['error'] = ''
            failed_runs = {r['model_profile']: r.get('error_code') for r in snap.get('runs') or []
                           if r.get('status') == 'failed'}
            for run in job.runs.select_related('profile'):
                code = failed_runs.get(pairing.profile_slug(run.profile))
                if run.status in ('pending', 'dispatched') and (code or fields['status'] != 'completed'):
                    run.status, run.error = 'refused', f'Rem0te: {code or "not run"}'[:500]
                    run.finished_at = timezone.now()
                    run.save(update_fields=['status', 'error', 'finished_at'])
        for k, v in fields.items():
            setattr(job, k, v)
        job.save(update_fields=list(fields) + ['updated_at'])
    return True


# --- the inference gateway, Rem0te's side --------------------------------------

def _resp(body_in: dict, status: str, **extra) -> dict:
    out = {'contract': protocol.CONTRACT, 'request_id': body_in['request_id'], 'job_id': body_in['job_id'],
           'organization_id': body_in['organization_id'], 'model_profile': body_in['model_profile'],
           'resolved_model': extra.pop('resolved_model', 'none'), 'status': status}
    out.update(extra)
    return out


def _refused(body_in, code, run=None, profile=None):
    resolved = (profile.model if profile else 'none')[:128] or 'none'
    if run is not None and run.status == 'pending':
        from psa_ai.models import AnalysisRun
        AnalysisRun.objects.filter(pk=run.pk, status='pending').update(
            status='refused', error=f'Refused by ClientSt0r: {code}'[:500], finished_at=timezone.now())
    return 200, _resp(body_in, 'refused', error_code=code[:64], resolved_model=resolved)


def _segments_ok(job, segments) -> Tuple[bool, List[dict]]:
    """Ticket segments must be the ticket ClientSt0r sent; endpoint segments
    only for the endpoint the job named. Returns (ok, endpoint segments)."""
    req = job.processor_request or {}
    t = req.get('ticket') or {}
    ticket_prefix = f'ticket:{t.get("id")}@{t.get("revision")}#'
    ep = (req.get('endpoint') or {}).get('rem0te_endpoint_id')
    endpoint_segments = []
    for s in segments:
        kind, ref = s.get('kind', ''), s.get('ref', '')
        if kind.startswith('ticket_'):
            if not ref.startswith(ticket_prefix):
                return False, []
        elif kind.startswith('endpoint_'):
            if not ep or not ref.startswith(f'endpoint:{ep}#') or s.get('author_role') != 'rem0te':
                return False, []
            endpoint_segments.append({'ref': ref[:256], 'kind': kind, 'text': s.get('text', '')[:4000]})
        else:
            return False, []
    return True, endpoint_segments


def ticket_segments(req: dict) -> List[dict]:
    """The ticket as segments, rebuilt from what ClientSt0r sent (Rem0te's
    ticketSegments(), same refs) — never from the text in the inference
    request."""
    t = req['ticket']
    ref = lambda part: f'ticket:{t["id"]}@{t["revision"]}#{part}'  # noqa: E731
    clean = lambda s, n: _REM0TE_CLEAN.sub('', s)[:n]  # noqa: E731
    out = [{'ref': ref('subject'), 'kind': 'ticket_subject', 'text': clean(t['subject'], 512)},
           {'ref': ref('body'), 'kind': 'ticket_body', 'text': clean(t['body'], 20000)}]
    for c in t.get('comments') or []:
        out.append({'ref': ref(f'comment:{c["id"]}'), 'kind': 'ticket_comment', 'author_role': c['author_role'],
                    'text': clean(c['body'], 8000)})
    return out


def prompt_text(job, endpoint_segments) -> str:
    lines = []
    for s in ticket_segments(job.processor_request) + list(endpoint_segments or []):
        who = f' ({s["author_role"]})' if s.get('author_role') else ''
        lines.append(f'[{s["ref"]}] {s["kind"]}{who}: {s["text"]}')
    if not endpoint_segments:
        lines.append('No device evidence is included. Work from the ticket alone.')
    return '\n'.join(lines)


def parse_output(text: str) -> dict:
    """Model text → a bounded analysis-output.v1 object (Rem0te re-checks it
    and demotes uncited facts). Raises InvalidResult."""
    from psa_ai.services.analysis_result import InvalidResult, _json_object
    data = _json_object(text)

    def s(v, n):
        return _CTRL.sub('', v).strip()[:n] if isinstance(v, str) else ''

    def refs(v):
        return [s(r, 256) for r in (v or []) if isinstance(r, str)][:10] if isinstance(v, list) else []
    category = s(data.get('category'), 64)
    if not category:
        raise InvalidResult('The model did not name a category.')
    out = {'category': category, 'summary': s(data.get('summary'), 1500), 'facts': [], 'hypotheses': [],
           'draft_reply': s(data.get('draft_reply'), 6000), 'next_steps': []}
    for f in (data.get('facts') or [])[:20] if isinstance(data.get('facts'), list) else []:
        if isinstance(f, dict) and s(f.get('statement'), 600):
            out['facts'].append({'statement': s(f.get('statement'), 600), 'evidence_refs': refs(f.get('evidence_refs'))})
    for h in (data.get('hypotheses') or [])[:10] if isinstance(data.get('hypotheses'), list) else []:
        if isinstance(h, dict) and s(h.get('statement'), 600):
            conf = h.get('confidence') if h.get('confidence') in ('low', 'medium', 'high') else 'low'
            out['hypotheses'].append({'statement': s(h.get('statement'), 600), 'confidence': conf,
                                      'evidence_refs': refs(h.get('evidence_refs'))})
    for n in (data.get('next_steps') or [])[:10] if isinstance(data.get('next_steps'), list) else []:
        if s(n, 400):
            out['next_steps'].append(s(n, 400))
    schema.validate('analysis-output', out)
    return out


def local_view(output: dict) -> dict:
    """The same output in the shape ClientSt0r's ticket UI, draft detection
    and fix suggestions already read (services/analysis_result.py)."""
    from psa_ai.services.evidence import redact
    return {
        'observed_facts': [{'text': redact(f['statement'], max_chars=500), 'evidence': f['evidence_refs'][:6]}
                           for f in output['facts']][:10],
        'likely_causes': [{'text': redact(h['statement'], max_chars=500), 'likelihood': h['confidence'],
                           'evidence': h['evidence_refs'][:6]} for h in output['hypotheses']][:5],
        'missing_information': [],
        'suggested_checks': [{'text': redact(n, max_chars=400)} for n in output['next_steps']][:8],
        'warnings': ['Rem0te checks these facts against the evidence it can resolve; see its findings below.'],
        'customer_replies': ([{'label': 'Draft reply', 'text': redact(output['draft_reply'], max_chars=3000)}]
                             if output['draft_reply'] else []),
        'summary': redact(output['summary'], max_chars=1500), 'category': output['category'],
        'rem0te_output': output,
    }


def system_prompt() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[2] / 'psa_ai' / 'prompts' / 'rem0te_ticket_triage_v1.md').read_text().strip()


def handle_inference(connection, body: dict) -> Tuple[int, dict]:
    """One model run for Rem0te. The caller has verified the request
    signature and consumed its nonce; the response it returns is signed by
    the caller over this request's nonce."""
    from core.ai_gate import ai_features_enabled
    from psa_ai.models import AnalysisJob, AnalysisRun
    from psa_ai.permissions import has_capability
    from psa_ai.services import budget, evidence as ev, gateway, gateway_keys, profiles

    errs = schema.errors('inference-request', body)
    if errs:
        return 400, {'error': {'code': 'INVALID_REQUEST', 'message': 'Not an inference-request: '
                               + '; '.join(errs[:3])}}
    if body['organization_id'] != pairing.organization_id(connection):
        return 403, {'error': {'code': 'FORBIDDEN', 'message': 'Organization is not this pairing\'s.'}}
    job = (AnalysisJob.objects.select_related('ticket', 'actor', 'organization', 'connection')
           .filter(connection=connection, protocol=AnalysisJob.PROTOCOL_REM0TE, processor_job_id=body['job_id'])
           .first())
    if job is None:
        # Possibly the submit response has not been stored yet: transient.
        return 503, {'error': {'code': 'JOB_NOT_KNOWN_YET', 'message': 'Job not known here (yet).'}}
    run = next((r for r in AnalysisRun.objects.select_related('profile').filter(job=job)
                if pairing.profile_slug(r.profile) == body['model_profile']), None)
    if run is None:
        return _refused(body, 'profile_not_in_job')
    profile = run.profile

    def answer(run):
        if run.status == 'succeeded':
            out = (run.result or {}).get('rem0te_output')
            if out:
                return 200, _resp(body, 'ok', output=out, resolved_model=(profile.model or 'unknown')[:128],
                                  usage={'input_tokens': run.input_tokens, 'output_tokens': run.output_tokens})
            return 200, _resp(body, 'error', error_code='output_missing', resolved_model=profile.model[:128] or 'x')
        if run.status in ('failed', 'refused'):
            return 200, _resp(body, 'refused' if run.status == 'refused' else 'error',
                              error_code=('refused' if run.status == 'refused' else 'model_failed'),
                              resolved_model=(profile.model or 'none')[:128])
        return None

    done = answer(run)
    if done:
        return done  # a retry: report, never run twice
    if run.status in ('dispatched', 'executing'):
        return _wait(run, answer)
    if job.is_terminal:
        return _refused(body, 'job_closed', run, profile)
    if job.expires_at <= timezone.now():
        return _refused(body, 'job_expired', run, profile)
    if not ai_features_enabled():
        return _refused(body, 'ai_disabled', run, profile)
    if not pairing.settings(connection)['enabled']:
        return _refused(body, 'pairing_disabled', run, profile)
    ticket = job.ticket
    if not (job.organization_id == ticket.organization_id == connection.organization_id):
        return _refused(body, 'tenant_mismatch', run, profile)
    capability = 'compare' if job.kind == job.KIND_COMPARE else 'analyze'
    if not has_capability(job.actor, job.organization, capability, ticket=ticket):
        return _refused(body, 'actor_not_permitted', run, profile)
    if ev.ticket_revision(ticket) != job.ticket_revision:
        return _refused(body, 'ticket_changed', run, profile)
    if ev.digest(job.evidence) != job.evidence_digest:
        return _refused(body, 'evidence_mismatch', run, profile)
    ok, endpoint_segments = _segments_ok(job, body['input']['untrusted_segments'])
    if not ok:
        return _refused(body, 'segment_unexpected', run, profile)
    policy = profiles.policy_for(job.organization)
    refusal = profiles.profile_refusal(profile, job.organization, job.actor, policy, connection)
    if refusal:
        return _refused(body, 'profile_refused', run, profile)
    _, _, cost = profiles.estimate(profile, len(prompt_text(job, endpoint_segments)))
    if cost and not budget.reserve(job.organization, cost, (policy.daily_budget_cents if policy else 0) * 100):
        return _refused(body, 'budget_exhausted', run, profile)
    claimed = AnalysisRun.objects.filter(pk=run.pk, status='pending', started_at__isnull=True).update(
        status='dispatched', started_at=timezone.now(), reserved_cost=cost, estimated_cost=cost,
        result={'rem0te_input': {'endpoint_segments': endpoint_segments}})
    if not claimed:
        budget.release(job.organization, cost)
        run.refresh_from_db()
        return answer(run) or _wait(run, answer)
    AnalysisJob.objects.filter(pk=job.pk, status__in=('created', 'submitted')).update(status='running')
    run.refresh_from_db()
    if gateway_keys.mode() == 'in_process' and gateway.claim_for_execution(run):
        gateway.execute(run)
    run.refresh_from_db()
    return answer(run) or _wait(run, answer)


def _wait(run, answer):
    deadline = time.monotonic() + WAIT_FOR_WORKER_SECONDS
    while time.monotonic() < deadline:
        run.refresh_from_db()
        done = answer(run)
        if done:
            return done
        time.sleep(0.5)
    # Still running: Rem0te retries a 503 with backoff and the retry is
    # answered from this same run.
    return 503, {'error': {'code': 'RUN_IN_PROGRESS', 'message': 'The model run is still in progress.'}}


def execute_run(run):
    """gateway.execute() for a Rem0te job: (text, tokens in, tokens out) →
    stored result. Called in whichever process holds provider keys."""
    from psa_ai.services import gateway
    from psa_ai.services.guardrails import wrap_user_content
    job, profile = run.job, run.profile
    endpoint_segments = ((run.result or {}).get('rem0te_input') or {}).get('endpoint_segments') or []
    text, t_in, t_out = gateway.call_provider(profile, system_prompt(),
                                              wrap_user_content(prompt_text(job, endpoint_segments)))
    return local_view(parse_output(text)), t_in, t_out


def staff_view(job, can_draft: bool) -> dict:
    """Rem0te's aggregated, staff-only result for the ticket page. Draft
    replies are dropped for a technician who may not draft."""
    res = dict(job.processor_result or {})
    if not res:
        return {}
    if not can_draft:
        res['draft_replies'] = []
    return {k: res.get(k) for k in ('visibility', 'facts', 'hypotheses', 'unsupported_claims', 'draft_replies',
                                    'next_steps', 'per_model', 'disagreements', 'untrusted_input_flags',
                                    'partial_failures', 'evidence')}


def json_bytes(obj) -> bytes:
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
