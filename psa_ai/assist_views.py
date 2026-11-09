"""
Ticket AI Assist: "Analyze ticket" and "Compare models" on the ticket page.

  GET  /psa/ai/assist/<ticket>/preview/?mode=analyze|compare
       What would be sent, to whom, at what cost — or why it can't run.
  POST /psa/ai/assist/<ticket>/submit/
       Start the job the technician just previewed.
  GET  /psa/ai/assist/job/<uuid>/
       The job's state and validated results (staff-only).

Every route resolves the ticket through the same scoped queryset as the
ticket page and re-checks technician access with the ticket itself, so a
direct ID from another customer or an unassigned ticket without
review_others gets 404, the same as a ticket that doesn't exist.

Nothing here posts to the ticket. Draft replies come back as text for the
composer; only the composer's normal Send publishes anything.
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from audit.models import AuditLog
from psa.feature_flags import require_psa_enabled
from psa.views import _scoped_ticket_qs

from .models import AnalysisJob, AnalysisRun
from .permissions import has_capability
from .services import evidence as ev, processor, profiles

JOB_LIFETIME = timedelta(minutes=15)
MAX_COMPARE = 4


def _ticket(request, ticket_number, capability):
    ticket = get_object_or_404(_scoped_ticket_qs(request), ticket_number=ticket_number)
    if not has_capability(request.user, ticket.organization, capability, ticket=ticket):
        raise Http404()
    return ticket


def _mode(value):
    return 'compare' if value == 'compare' else 'analyze'


def _profile_view(profile, evidence_chars):
    _, _, cost = profiles.estimate(profile, evidence_chars)
    return {'id': profile.pk, 'name': profile.name, 'provider': profile.get_provider_display(),
            'model': profile.model, 'location': 'On-premises' if profile.location == 'local' else 'Cloud',
            'credential': profile.get_credential_owner_display(), 'estimated_cost_cents': round(cost / 100, 2)}


@login_required
@require_psa_enabled
@require_GET
def preview(request, ticket_number):
    mode = _mode(request.GET.get('mode'))
    ticket = _ticket(request, ticket_number, 'view_output')
    ok, reasons = profiles.availability(ticket, request.user, mode)
    body = {'mode': mode, 'available': ok, 'reasons': reasons}
    if not ok:
        return JsonResponse(body)
    evidence = ev.build_evidence(ticket)
    chars = len(ev.prompt_text(evidence))
    usable = profiles.usable_profiles(ticket.organization, request.user)
    chosen = [profiles.default_profile(ticket.organization, request.user)] if mode == 'analyze' else usable[:MAX_COMPARE]
    from integrations.providers.rmm.rem0te import integration_settings
    conn = profiles.processor_for(ticket.organization)
    remaining = profiles.budget_remaining(ticket.organization)
    body.update({
        'evidence': {'items': evidence['items'], 'excluded': evidence['excluded'],
                     'redactions': evidence['redactions'], 'asset': evidence['asset']},
        'evidence_digest': ev.digest(evidence),
        'ticket_revision': ev.ticket_revision(ticket),
        'processor': {'name': conn.name, 'site': integration_settings(conn)['site'],
                      'location': integration_settings(conn)['location']},
        'profiles': [_profile_view(p, chars) for p in chosen],
        'choosable': [_profile_view(p, chars) for p in usable] if mode == 'compare' else [],
        'budget_remaining_cents': None if remaining is None else round(remaining / 100, 2),
        'idempotency_key': uuid.uuid4().hex,
    })
    return JsonResponse(body)


def _bad(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


@login_required
@require_psa_enabled
@require_POST
def submit(request, ticket_number):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        data = request.POST
    mode = _mode(data.get('mode'))
    ticket = _ticket(request, ticket_number, 'analyze')
    ok, reasons = profiles.availability(ticket, request.user, mode)
    if not ok:
        return _bad(' '.join(reasons), 403)
    key = str(data.get('idempotency_key') or '')
    if not (8 <= len(key) <= 64) or not key.replace('-', '').isalnum():
        return _bad('Missing or malformed idempotency key; preview again.')

    evidence = ev.build_evidence(ticket)
    digest = ev.digest(evidence)
    if str(data.get('evidence_digest') or '') != digest:
        return _bad('The ticket changed since you previewed it. Preview again before sending.', 409)

    usable = {p.pk: p for p in profiles.usable_profiles(ticket.organization, request.user)}
    if mode == 'analyze':
        chosen = [profiles.default_profile(ticket.organization, request.user)]
    else:
        ids = [int(i) for i in (data.get('profile_ids') or []) if str(i).isdigit()]
        chosen = [usable[i] for i in dict.fromkeys(ids) if i in usable][:MAX_COMPARE]
        if len(chosen) < 2:
            return _bad('Choose at least two allowed models to compare.')
    if not chosen or chosen[0] is None:
        return _bad('No AI model profile is allowed for this customer.', 403)

    conn = profiles.processor_for(ticket.organization)
    from integrations.providers.rmm.rem0te import BUSINESS_PIN
    payload_digest = ev.digest({'ticket': ticket.pk, 'mode': mode, 'evidence': digest,
                                'profiles': sorted(p.pk for p in chosen), 'connection': conn.pk})
    existing = AnalysisJob.objects.filter(actor=request.user, idempotency_key=key).first()
    if existing is not None:
        if existing.payload_digest != payload_digest:
            return _bad('That request was already used for a different analysis.', 409)
        return JsonResponse({'ok': True, 'job_id': str(existing.id), 'status': existing.status, 'repeat': True})
    try:
        with transaction.atomic():
            job = AnalysisJob.objects.create(
                organization=ticket.organization, ticket=ticket, ticket_revision=ev.ticket_revision(ticket),
                actor=request.user, kind=mode, connection=conn,
                business_id=str((conn.field_mappings or {}).get(BUSINESS_PIN) or ''),
                evidence=evidence, evidence_digest=digest, payload_digest=payload_digest,
                idempotency_key=key, expires_at=timezone.now() + JOB_LIFETIME)
            for p in chosen:
                AnalysisRun.objects.create(job=job, profile=p)
    except IntegrityError:  # a concurrent double-click won the race
        job = AnalysisJob.objects.get(actor=request.user, idempotency_key=key)
        if job.payload_digest != payload_digest:
            return _bad('That request was already used for a different analysis.', 409)
        return JsonResponse({'ok': True, 'job_id': str(job.id), 'status': job.status, 'repeat': True})

    AuditLog.log(user=request.user, action='create', organization=ticket.organization,
                 object_type='psa_ai.AnalysisJob', object_repr=f'AI {mode} on {ticket.ticket_number}'[:255],
                 description=f'AI {mode} requested on {ticket.ticket_number}: '
                             f'{", ".join(p.name for p in chosen)} via {conn.name}',
                 path=request.path,
                 extra_data={'job': str(job.id), 'profiles': [p.pk for p in chosen], 'evidence_digest': digest,
                             'redactions': evidence['redactions']})
    status = processor.submit(job, request)
    return JsonResponse({'ok': True, 'job_id': str(job.id), 'status': status})


def _run_view(run):
    return {'profile': run.profile.name, 'provider': run.profile.get_provider_display(), 'status': run.status,
            'error': run.error, 'result': run.result if run.status == 'succeeded' else None,
            'cost_cents': round(run.actual_cost / 100, 2), 'tokens': run.input_tokens + run.output_tokens}


@login_required
@require_psa_enabled
@require_GET
def job_status(request, job_id):
    job = get_object_or_404(AnalysisJob.objects.select_related('ticket', 'organization'), pk=job_id)
    if not _scoped_ticket_qs(request).filter(pk=job.ticket_id, organization_id=job.organization_id).exists():
        raise Http404()
    if not has_capability(request.user, job.organization, 'view_output', ticket=job.ticket):
        raise Http404()
    job = processor.poll(job)
    can_draft = has_capability(request.user, job.organization, 'draft', ticket=job.ticket)
    runs = [_run_view(r) for r in job.runs.select_related('profile')]
    if not can_draft:
        for r in runs:
            if r['result']:
                r['result'] = dict(r['result'], customer_replies=[])
    return JsonResponse({
        'job_id': str(job.id), 'status': job.status, 'status_label': job.get_status_display(),
        'kind': job.kind, 'terminal': job.is_terminal, 'error': job.error,
        'disagreements': job.disagreements, 'runs': runs,
        'stale': job.ticket_revision != ev.ticket_revision(job.ticket),
        'can_send_ai_reply': has_capability(request.user, job.organization, 'send_reply', ticket=job.ticket),
        'evidence': [{'id': i['id'], 'kind': i['kind']} for i in job.evidence.get('items') or []],
    })
