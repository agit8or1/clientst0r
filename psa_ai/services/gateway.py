"""
The inference gateway: the only code that sends ticket evidence to a model.

The paired RMM (any ticket-rmm-v1 processor; rem0te is the reference)
processes an analysis job and asks for each model run with a signed
POST /api/integration/v1/inference (psa_ai/integration_api.py). Before any
provider is called, `dispatch()` re-checks, against current database rows:

  * the job belongs to the calling pairing and isn't expired or done;
  * the delegation token names this job, its actor, customer and ticket,
    and hasn't expired;
  * the actor is still an active technician with this capability at this
    customer and on this ticket (technician access, re-read now — a
    demotion while the job sat in a queue stops it here);
  * tenant binding: job, ticket and pairing are one customer, and the
    pairing's pinned tenant is the job's;
  * the ticket hasn't changed since the technician previewed the evidence;
  * the evidence digest the RMM quotes is the job's, and the stored evidence
    still hashes to it;
  * the profile is one the job asked for and is still usable (enabled,
    allowed by policy, credential owner, local-only);
  * the customer's daily budget has room (atomic reservation).

It then claims the run with a conditional UPDATE, so a retry, a double
click or two processors racing can only ever produce one provider call.

The prompt is built from the stored evidence only — never from anything
the RMM sends. Model output is parsed as untrusted (analysis_result.py).
The provider key is opened by the gateway process (gateway_keys.py) and
never returned to the RMM or the browser.

Destinations: Anthropic and OpenAI only at their fixed API hosts on public
addresses; Ollama only at the origin an administrator approved, with LAN
addresses allowed for it and nothing else. Redirects are not followed, and
cloud metadata addresses are refused under every policy (core.safe_http).
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

import requests
from django.core import signing
from django.db import transaction
from django.utils import timezone

from core.safe_http import BlockedDestinationError, OutboundPolicy, PUBLIC_WEB, guard_session

from . import analysis_result, budget, evidence as ev, gateway_keys, profiles
from .guardrails import wrap_user_content

logger = logging.getLogger('psa_ai')

DELEGATION_SALT = 'ticket-rmm-v1.delegation'
DELEGATION_MAX_AGE = 15 * 60
WORKER_WAIT_SECONDS = 30
MAX_RESPONSE_BYTES = 1024 * 1024
CLOUD_ORIGINS = {'anthropic': 'https://api.anthropic.com:443', 'openai': 'https://api.openai.com:443'}
_LOOPBACK = {'localhost', '127.0.0.1', '::1', '[::1]'}


class GatewayRefusal(Exception):
    def __init__(self, code, message, status=403):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def origin(url) -> str:
    try:
        parts = urlsplit((url or '').strip())
    except ValueError:
        return ''
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return ''
    port = parts.port or (443 if parts.scheme == 'https' else 80)
    host = parts.hostname.lower()
    return f'{parts.scheme}://{"[" + host + "]" if ":" in host else host}:{port}'


# --- delegation ----------------------------------------------------------------

def delegation_token(job) -> str:
    return signing.dumps({'job': str(job.id), 'actor': job.actor_id, 'org': job.organization_id,
                          'ticket': job.ticket_id}, salt=DELEGATION_SALT)


def _check_delegation(token, job):
    try:
        data = signing.loads(token or '', salt=DELEGATION_SALT, max_age=DELEGATION_MAX_AGE)
    except signing.SignatureExpired:
        raise GatewayRefusal('delegation_expired', 'The delegated identity has expired.', 401)
    except signing.BadSignature:
        raise GatewayRefusal('delegation_invalid', 'The delegated identity is not valid.', 401)
    want = {'job': str(job.id), 'actor': job.actor_id, 'org': job.organization_id, 'ticket': job.ticket_id}
    if data != want:
        raise GatewayRefusal('delegation_mismatch', 'The delegated identity is for a different job.', 403)


# --- dispatch (web process) ----------------------------------------------------

def _capability(job):
    return 'compare' if job.kind == job.KIND_COMPARE else 'analyze'


def dispatch(connection, job_id, profile_id, delegation, evidence_digest):
    """Validate an inference request and claim its run. Returns the run."""
    from integrations.ticket_rmm import TENANT_PIN, settings as integration_settings
    from psa_ai.models import AnalysisJob, AnalysisRun
    from psa_ai.permissions import has_capability
    from core.ai_gate import ai_features_enabled

    job = (AnalysisJob.objects.select_related('ticket', 'actor', 'organization', 'connection')
           .filter(pk=job_id, connection=connection).first())
    if job is None:
        raise GatewayRefusal('job_unknown', 'No such job for this pairing.', 404)
    if not integration_settings(connection)['enabled']:
        raise GatewayRefusal('pairing_disabled', 'This pairing is switched off.')
    if job.is_terminal:
        # An identical retry after the job finished still learns how its run
        # ended (reporting only, nothing is re-checked or re-run).
        _check_delegation(delegation, job)
        done = AnalysisRun.objects.filter(job=job, profile_id=profile_id,
                                          status__in=('succeeded', 'failed', 'refused')).first()
        if done is not None and evidence_digest == job.evidence_digest:
            return done
        raise GatewayRefusal('job_closed', 'This job is already finished.', 409)
    if job.expires_at <= timezone.now():
        _expire(job)
        raise GatewayRefusal('job_expired', 'This job has expired.', 410)
    _check_delegation(delegation, job)
    if not ai_features_enabled():
        raise GatewayRefusal('ai_disabled', 'AI features are turned off.')
    ticket = job.ticket
    if not (job.organization_id == ticket.organization_id == connection.organization_id):
        raise GatewayRefusal('tenant_mismatch', 'Job, ticket and pairing are not one customer.')
    if str((connection.field_mappings or {}).get(TENANT_PIN) or '') != job.business_id:
        raise GatewayRefusal('business_mismatch', 'The pairing now answers for a different business.')
    if not has_capability(job.actor, job.organization, _capability(job), ticket=ticket):
        raise GatewayRefusal('actor_not_permitted', "The technician's access no longer allows this.")
    if ev.ticket_revision(ticket) != job.ticket_revision:
        raise GatewayRefusal('ticket_changed', 'The ticket changed after the evidence was previewed.', 409)
    if evidence_digest != job.evidence_digest or ev.digest(job.evidence) != job.evidence_digest:
        raise GatewayRefusal('evidence_mismatch', 'The evidence does not match the job.', 409)

    run = AnalysisRun.objects.select_related('profile').filter(job=job, profile_id=profile_id).first()
    if run is None:
        raise GatewayRefusal('profile_not_in_job', 'That model is not part of this job.', 404)
    if run.status in ('succeeded', 'failed', 'refused', 'dispatched', 'executing'):
        return run  # an identical retry: report, never run twice
    policy = profiles.policy_for(job.organization)
    refusal = profiles.profile_refusal(run.profile, job.organization, job.actor, policy, connection)
    if refusal:
        _refuse(run, refusal)
        raise GatewayRefusal('profile_refused', refusal)

    _, _, cost = profiles.estimate(run.profile, len(ev.prompt_text(job.evidence)))
    if cost and not budget.reserve(job.organization, cost, (policy.daily_budget_cents if policy else 0) * 100):
        _refuse(run, "Today's AI budget for this customer is used up.")
        raise GatewayRefusal('budget_exhausted', "Today's AI budget for this customer is used up.", 429)
    claimed = AnalysisRun.objects.filter(pk=run.pk, status='pending', started_at__isnull=True).update(
        status='dispatched', started_at=timezone.now(), reserved_cost=cost, estimated_cost=cost)
    if not claimed:
        budget.release(job.organization, cost)
        run.refresh_from_db()
        return run
    AnalysisJob.objects.filter(pk=job.pk, status='submitted').update(status='running')
    run.refresh_from_db()
    return run


def _refuse(run, reason):
    from psa_ai.models import AnalysisRun
    AnalysisRun.objects.filter(pk=run.pk, status='pending').update(
        status='refused', error=reason[:500], finished_at=timezone.now())
    finish_job(run.job)


def _expire(job):
    from psa_ai.models import AnalysisJob, AnalysisRun
    AnalysisRun.objects.filter(job=job, status='pending').update(status='refused', error='Job expired.',
                                                                 finished_at=timezone.now())
    AnalysisJob.objects.filter(pk=job.pk).exclude(status__in=AnalysisJob.TERMINAL).update(status='expired')


def serve(connection, job_id, profile_id, delegation, evidence_digest):
    """dispatch(), then run the model here (in-process mode) or wait for the
    worker. Returns the run, finished or still running."""
    run = dispatch(connection, job_id, profile_id, delegation, evidence_digest)
    if run.status != 'dispatched' and run.status != 'executing':
        return run
    if gateway_keys.mode() == 'in_process':
        if claim_for_execution(run):
            execute(run)
        run.refresh_from_db()
        return run
    deadline = time.monotonic() + WORKER_WAIT_SECONDS
    while time.monotonic() < deadline:
        run.refresh_from_db()
        if run.status not in ('dispatched', 'executing'):
            return run
        time.sleep(0.5)
    return run


# --- execution (gateway process) ----------------------------------------------

def claim_for_execution(run) -> bool:
    from psa_ai.models import AnalysisRun
    return AnalysisRun.objects.filter(pk=run.pk, status='dispatched').update(status='executing') == 1


ANALYSIS_PROMPT = 'system_analysis.md'
REM0TE_PROMPT = 'rem0te_ticket_triage_v1.md'


def _system_prompt():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / 'prompts' / ANALYSIS_PROMPT).read_text()
    return text.replace('Evidence:\n\n{{context}}', 'The evidence is in the user message.').strip()


def destination(profile):
    """(base URL, OutboundPolicy) the gateway may call for this profile."""
    if profile.provider in CLOUD_ORIGINS:
        return CLOUD_ORIGINS[profile.provider].replace(':443', ''), PUBLIC_WEB
    if profile.provider == 'ollama':
        approved = profile.approved_destination
        if not approved or origin(profile.base_url) != approved:
            raise GatewayRefusal('destination_unapproved', "This Ollama address hasn't been approved.")
        host = urlsplit(approved).hostname or ''
        return approved, OutboundPolicy(allow_lan=True, allow_local=host in _LOOPBACK, allowed_ports=None)
    raise GatewayRefusal('provider_unknown', 'Unknown provider.')


def _session(policy):
    s = requests.Session()
    s.trust_env = False
    s.max_redirects = 0
    return guard_session(s, policy)


def _post(session, url, **kw):
    r = session.post(url, allow_redirects=False, timeout=(5, 90), stream=True, **kw)
    if 300 <= r.status_code < 400:
        raise GatewayRefusal('redirect_refused', 'The provider answered with a redirect; not followed.', 502)
    body = b''
    for chunk in r.iter_content(65536):
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise GatewayRefusal('response_too_large', 'The provider response was too large.', 502)
    r._content = body
    if r.status_code >= 400:
        raise GatewayRefusal('provider_error', f'The provider answered HTTP {r.status_code}.', 502)
    return r.json()


def call_provider(profile, system, user_text):
    """(text, input tokens, output tokens)."""
    base, policy = destination(profile)
    session = _session(policy)
    if profile.provider == 'anthropic':
        data = _post(session, f'{base}/v1/messages', headers={
            'x-api-key': gateway_keys.unseal(profile.sealed_api_key), 'anthropic-version': '2023-06-01',
            'content-type': 'application/json'}, json={
            'model': profile.model, 'max_tokens': profile.max_output_tokens, 'system': system,
            'messages': [{'role': 'user', 'content': user_text}]})
        text = ''.join(b.get('text', '') for b in data.get('content') or [] if b.get('type') == 'text')
        usage = data.get('usage') or {}
        return text, int(usage.get('input_tokens') or 0), int(usage.get('output_tokens') or 0)
    if profile.provider == 'openai':
        data = _post(session, f'{base}/v1/chat/completions', headers={
            'Authorization': f'Bearer {gateway_keys.unseal(profile.sealed_api_key)}'}, json={
            'model': profile.model, 'max_completion_tokens': profile.max_output_tokens,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user_text}]})
        text = ((data.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
        usage = data.get('usage') or {}
        return text, int(usage.get('prompt_tokens') or 0), int(usage.get('completion_tokens') or 0)
    headers = {}
    if profile.sealed_api_key:
        headers['Authorization'] = f'Bearer {gateway_keys.unseal(profile.sealed_api_key)}'
    data = _post(session, f'{base}/api/chat', headers=headers, json={
        'model': profile.model, 'stream': False, 'options': {'num_predict': profile.max_output_tokens},
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user_text}]})
    return ((data.get('message') or {}).get('content') or '', int(data.get('prompt_eval_count') or 0),
            int(data.get('eval_count') or 0))


def execute(run):
    """Run one claimed model call and store the validated result."""
    from psa_ai.models import AnalysisRun
    run = AnalysisRun.objects.select_related('job', 'profile', 'job__organization').get(pk=run.pk)
    job, profile = run.job, run.profile
    status, result, error, t_in, t_out = 'failed', {}, '', 0, 0
    # Record what is about to run before the provider is called, so a run
    # that fails still shows which model and prompt version it used.
    from .prompt_versions import prompt_version
    AnalysisRun.objects.filter(pk=run.pk).update(
        resolved_model=f'{profile.provider}/{profile.model}'[:150],
        prompt_version=prompt_version(ANALYSIS_PROMPT if job.protocol != job.PROTOCOL_REM0TE
                                      else REM0TE_PROMPT))
    try:
        if job.protocol == job.PROTOCOL_REM0TE:
            from integrations.rem0te.jobs import execute_run
            result, t_in, t_out = execute_run(run)
        else:
            text, t_in, t_out = call_provider(profile, _system_prompt(),
                                              wrap_user_content(ev.prompt_text(job.evidence)))
            result = analysis_result.parse(text, ev.evidence_ids(job.evidence))
        status = 'succeeded'
    except GatewayRefusal as e:
        error = e.message
    except BlockedDestinationError:
        error = 'The provider address is not an allowed destination.'
    except gateway_keys.GatewayKeyError as e:
        error = str(e)
    except analysis_result.InvalidResult as e:
        error = str(e)
    except requests.RequestException:
        error = 'Could not reach the provider.'
    except Exception:
        logger.exception('analysis run %s failed', run.pk)
        error = 'The model run failed.'
    cost = profiles.actual_cost(profile, t_in, t_out) if (t_in or t_out) else 0
    budget.settle(job.organization, run.reserved_cost, cost)
    AnalysisRun.objects.filter(pk=run.pk).update(
        status=status, result=result, error=error[:500], input_tokens=t_in, output_tokens=t_out,
        actual_cost=min(cost, run.reserved_cost), finished_at=timezone.now())
    finish_job(job)


def finish_job(job):
    """Close the job once every run has an outcome."""
    from psa_ai.models import AnalysisJob
    if getattr(job, 'protocol', '') == AnalysisJob.PROTOCOL_REM0TE:
        # Rem0te aggregates the runs and closes the job with a signed
        # terminal event (integrations/rem0te/jobs.py); a local run
        # finishing does not end it.
        return job
    with transaction.atomic():
        job = AnalysisJob.objects.select_for_update().get(pk=job.pk)
        if job.is_terminal:
            return job
        runs = list(job.runs.select_related('profile'))
        if any(r.status in ('pending', 'dispatched', 'executing') for r in runs):
            return job
        ok = [r for r in runs if r.status == 'succeeded']
        job.status = 'completed' if len(ok) == len(runs) else ('partial' if ok else 'failed')
        job.disagreements = analysis_result.disagreements(ok) if len(ok) > 1 else []
        if not ok:
            job.error = '; '.join(sorted({r.error for r in runs if r.error}))[:1000]
        job.save(update_fields=['status', 'disagreements', 'error', 'updated_at'])
    return job


def run_worker_once(limit=10) -> int:
    """Execute dispatched runs. Called in a loop by `ai_gateway_worker`."""
    from psa_ai.models import AnalysisRun
    if not gateway_keys.is_worker_process():
        raise RuntimeError('run_worker_once runs only in the AI gateway worker.')
    done = 0
    for run in AnalysisRun.objects.filter(status='dispatched').order_by('started_at')[:limit]:
        if claim_for_execution(run):
            execute(run)
            done += 1
    return done
