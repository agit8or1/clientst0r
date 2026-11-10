"""
ClientSt0r's half of ticket-rmm-v1: the two routes the paired RMM calls
(any provider that implements the contract; rem0te is the reference).

  POST /api/integration/v1/inference   run one model for one job
  POST /api/integration/v1/events      a signed job event (`job_id`), or a
                                       handoff / diagnostic / fix-referral
                                       status event (`request_id`)

Both require a signed request from a live pairing (integration_auth.py);
no session, cookie or API key works here, and CSRF does not apply because
nothing here acts on a browser's ambient credentials.

Inference answers with the run's status and token counts — never the
provider key, and never the analysis text, which stays in ClientSt0r for
the technician. An identical retry of a claimed run returns that run's
status instead of calling the model again.
"""
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import integration_auth
from .services.gateway import GatewayRefusal, serve

logger = logging.getLogger('psa_ai')

MAX_BODY = 64 * 1024


def _error(code, message, status):
    return JsonResponse({'error': code, 'message': message}, status=status)


def _authenticated(request):
    if len(request.body) > MAX_BODY:
        raise integration_auth.AuthError('body too large')
    return integration_auth.verify_request(request)


def _json(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _run_view(run):
    return {'job_id': str(run.job_id), 'profile_id': run.profile_id, 'status': run.status,
            'input_tokens': run.input_tokens, 'output_tokens': run.output_tokens,
            'error': run.error if run.status in ('failed', 'refused') else ''}


@csrf_exempt
@require_POST
def inference(request):
    try:
        conn = _authenticated(request)
    except integration_auth.AuthError as e:
        logger.warning('integration inference refused: %s', e)
        return _error('unauthenticated', 'Request signature not accepted.', 401)
    data = _json(request)
    if data is None or data.get('contract') != 'ticket-rmm-v1':
        return _error('bad_request', 'Expected a ticket-rmm-v1 JSON object.', 400)
    try:
        run = serve(conn, str(data.get('job_id') or ''), int(data.get('profile_id') or 0),
                    str(data.get('delegation') or ''), str(data.get('evidence_digest') or ''))
    except GatewayRefusal as e:
        return _error(e.code, e.message, e.status)
    except (ValueError, TypeError):
        return _error('bad_request', 'job_id, profile_id, delegation and evidence_digest are required.', 400)
    except Exception:
        logger.exception('inference failed')
        return _error('internal', 'The gateway failed.', 500)
    body = _run_view(run)
    if run.status in ('dispatched', 'executing'):
        body['retry_after'] = 5
        return JsonResponse(body, status=202)
    return JsonResponse(body)


@csrf_exempt
@require_POST
def events(request):
    from .models import AnalysisJob, ProcessorEvent
    from .services.processor import EVENT_TYPES, apply_event
    from django.db import IntegrityError, transaction
    if len(request.body) > MAX_BODY:
        return _error('too_large', f'Event bodies are limited to {MAX_BODY // 1024} KiB.', 413)
    try:
        conn = _authenticated(request)
    except integration_auth.AuthError as e:
        logger.warning('integration event refused: %s', e)
        return _error('unauthenticated', 'Request signature not accepted.', 401)
    data = _json(request)
    if data is None:
        return _error('bad_request', 'Expected a JSON object.', 400)
    if 'request_id' in data:
        return _request_event(conn, data)
    event_id, event_type, seq = str(data.get('event_id') or '')[:100], str(data.get('type') or ''), data.get('sequence')
    if not event_id or event_type not in EVENT_TYPES or not isinstance(seq, int) or seq < 1:
        return _error('bad_request', 'event_id, a known type and a positive sequence are required.', 400)
    job = AnalysisJob.objects.filter(pk=str(data.get('job_id') or ''), connection=conn).first() \
        if _is_uuid(data.get('job_id')) else None
    if job is None:
        return _error('job_unknown', 'No such job for this pairing.', 404)
    try:
        with transaction.atomic():
            event = ProcessorEvent.objects.create(job=job, event_id=event_id, sequence=seq, event_type=event_type)
    except IntegrityError:
        return JsonResponse({'status': 'duplicate'})
    applied = apply_event(job, event_type, seq)
    if applied:
        ProcessorEvent.objects.filter(pk=event.pk).update(applied=True)
    return JsonResponse({'status': 'applied' if applied else 'recorded'})


def _request_event(conn, data):
    """A status event for a handoff, diagnostic or fix referral. It moves
    only that request's own status; nothing here touches the ticket."""
    from django.db import IntegrityError, transaction
    from .models import RMMRequest, RMMRequestEvent
    from .services.rmm_actions import REQUEST_EVENT_TYPES, apply_event
    event_id, event_type, seq = str(data.get('event_id') or '')[:100], str(data.get('type') or ''), data.get('sequence')
    if (not event_id or event_type not in REQUEST_EVENT_TYPES or not isinstance(seq, int) or isinstance(seq, bool)
            or seq < 1):
        return _error('bad_request', 'event_id, a known type and a positive sequence are required.', 400)
    req = RMMRequest.objects.select_related('actor').filter(
        pk=str(data.get('request_id') or ''), connection=conn).first() if _is_uuid(data.get('request_id')) else None
    if req is None:
        return _error('request_unknown', 'No such request for this pairing.', 404)
    from integrations.ticket_rmm import settings as pairing
    if req.tenant_id != pairing(conn)['tenant_id']:
        return _error('tenant_mismatch', 'The pairing now answers for a different tenant.', 403)
    if not event_type.startswith({'handoff': 'handoff.', 'diagnostic': 'diagnostic.',
                                  'fix_referral': 'fix.'}[req.kind]):
        return _error('wrong_kind', f'That event type does not apply to a {req.get_kind_display().lower()}.', 409)
    try:
        with transaction.atomic():
            event = RMMRequestEvent.objects.create(request=req, event_id=event_id, sequence=seq,
                                                   event_type=event_type)
    except IntegrityError:
        return JsonResponse({'status': 'duplicate'})
    applied = apply_event(req, event_type, seq, data)
    if applied:
        RMMRequestEvent.objects.filter(pk=event.pk).update(applied=True)
    return JsonResponse({'status': 'applied' if applied else 'recorded'})


def _is_uuid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


app_name = 'integration_api'
urlpatterns = [
    path('inference', inference, name='inference'),
    path('events', events, name='events'),
]
