"""
Generate AI triage guidance for a PSA ticket. Read-only advisory output —
the model proposes investigation steps, likely causes, questions to ask
the customer, and references to consult. NOTHING is applied automatically.

Mirrors the structure of `reply_generator.py`:
  * Same guardrails: master switch, subject blocklist, per-user rate limit,
    daily token quota, output content filter.
  * Same context-builder (vault data is FORBIDDEN — `context_builder` is
    the single source of truth and the no-secrets test exercises it).
  * Persists exactly one `AISuggestion(kind='triage')` row per request
    (success, failure, or blocked).
  * The model, key, budget and sharing rules come from the customer's AI
    policy, through the AI gateway (services/policy_call.py, security
    finding S2); the install-wide key is not used.
"""
from __future__ import annotations

from core.ai_models import sampling_kwargs

import logging
import os
from decimal import Decimal
from pathlib import Path

from .context_builder import build_ticket_context
from .guardrails import (
    output_passes_filter, quota_exceeded, record_usage,
    subject_is_blocked, user_rate_exceeded,
)
from . import policy_call
from .reply_generator import SafetyFailure, prepare_policy_call, split_system_prompt


logger = logging.getLogger('psa_ai.triage_generator')

PROMPTS_DIR = Path(__file__).resolve().parent.parent / 'prompts'
SYSTEM_PROMPT_PATH = PROMPTS_DIR / 'system_triage.md'


def _prompt_version():
    """File name + content hash of the system prompt (services/prompt_versions.py)."""
    from .prompt_versions import prompt_version
    return prompt_version(SYSTEM_PROMPT_PATH.name)

# Triage uses a fixed cheaper/faster model regardless of CLAUDE_MODEL —
# advisory output doesn't need Sonnet-class reasoning, and lower
# temperature reduces hallucination of vendor-specific commands.
TRIAGE_MODEL = 'claude-haiku-4-5-20251001'
TRIAGE_TEMPERATURE = 0.3
TRIAGE_MAX_OUTPUT_TOKENS = 1500

# Per-spec dedicated triage rate limits (independent of the per-min
# reply/action limit). The shared org/user daily token bucket still
# enforces total spend.
TRIAGE_USER_HOURLY_LIMIT = 10
TRIAGE_ORG_DAILY_LIMIT = 50


def _load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text()


def _system_setting():
    from core.models import SystemSetting
    return SystemSetting.get_settings()


def _triage_user_hourly_exceeded(user) -> tuple[bool, str]:
    """True when this user has already requested >= 10 triage suggestions
    in the trailing 60 minutes."""
    from datetime import timedelta
    from django.utils import timezone
    from psa_ai.models import AISuggestion
    cutoff = timezone.now() - timedelta(hours=1)
    count = AISuggestion.objects.filter(
        kind='triage', requested_by=user, created_at__gte=cutoff,
    ).count()
    if count >= TRIAGE_USER_HOURLY_LIMIT:
        return True, (
            f'Triage rate limit hit ({count}/{TRIAGE_USER_HOURLY_LIMIT} '
            f'in the last hour). Try again later.'
        )
    return False, ''


def _triage_org_daily_exceeded(org) -> tuple[bool, str]:
    """True when this org has already requested >= 50 triage suggestions
    today."""
    from django.utils import timezone
    from psa_ai.models import AISuggestion
    today = timezone.localdate()
    count = AISuggestion.objects.filter(
        kind='triage', organization=org, created_at__date=today,
    ).count()
    if count >= TRIAGE_ORG_DAILY_LIMIT:
        return True, (
            f'Org triage daily limit hit '
            f'({count}/{TRIAGE_ORG_DAILY_LIMIT} today).'
        )
    return False, ''


def generate_triage_for_ticket(ticket, *, requested_by, request=None):
    """
    Run the guardrails + generate pipeline for triage. Always persists
    exactly one `AISuggestion(kind='triage')` row.

    Raises `SafetyFailure` for guardrails that should NOT leave a
    persisted suggestion (rate limit, quota, missing API key, AI
    disabled, permission denied, cross-tenant) so the caller can show a
    flash and redirect without polluting the suggestions list.

    Returns the persisted `AISuggestion` instance otherwise.
    """
    from psa_ai.models import AISuggestion
    from psa_ai.permissions import can_request_triage
    from audit.models import AuditLog

    ss = _system_setting()
    org = ticket.organization

    # 0. Master switch.
    if not ss.psa_ai_enabled:
        raise SafetyFailure('PSA AI Assist is disabled in Settings.')

    # 0a. Tenant-isolation defence-in-depth: the view already filters by
    # the user's org, but reject explicitly here too.
    if requested_by is not None and not requested_by.is_superuser:
        if hasattr(requested_by, 'memberships'):
            org_ids = list(
                requested_by.memberships.filter(is_active=True)
                .values_list('organization_id', flat=True)
            )
            if org.id not in org_ids and not getattr(
                getattr(requested_by, 'profile', None), 'is_staff_user', lambda: False
            )():
                raise SafetyFailure(
                    'Cross-tenant triage request rejected.'
                )

    # 0b. Permission gate — role-template `psa_ai_request_triage` flag
    # (defaults to True for any tech in the org).
    if not can_request_triage(requested_by, org, request=request):
        raise SafetyFailure(
            "You don't have permission to request AI triage for this ticket."
        )

    # 1. Subject blocklist.
    blocked, reason = subject_is_blocked(
        ticket.subject or '', ss.psa_ai_blocked_subject_keywords or '',
    )
    if blocked:
        return _persist_blocked(ticket, requested_by, reason)

    # 2. Per-user generations/min rate-limit (shared with reply/action).
    over, reason = user_rate_exceeded(
        requested_by, int(ss.psa_ai_per_user_rate_per_min or 0),
    )
    if over:
        raise SafetyFailure(reason)

    # 2a. Triage-specific per-user hourly limit.
    over, reason = _triage_user_hourly_exceeded(requested_by)
    if over:
        raise SafetyFailure(reason)

    # 2b. Triage-specific per-org daily limit.
    over, reason = _triage_org_daily_exceeded(org)
    if over:
        raise SafetyFailure(reason)

    # 3. Daily token quota check (shared bucket — no separate triage budget).
    over, reason = quota_exceeded(
        org, requested_by,
        est_tokens=4000,  # ~2.5k input + 1.5k output worst case
        org_limit=int(ss.psa_ai_daily_token_limit or 0),
        user_limit=int(ss.psa_ai_per_user_daily_limit or 0),
    )
    if over:
        raise SafetyFailure(reason)

    # 4. Build context (sanitises every user-supplied string; vault
    # excluded — the no-secrets test enforces this).
    # 5. The customer's AI policy picks the model and key (never the
    # install-wide key) and its sharing rules shape the context (S2).
    policy, profile = prepare_policy_call(ticket, requested_by)
    ctx = build_ticket_context(ticket, policy=policy)

    # 6. Model call through the AI gateway, against the customer's budget.
    system_prompt = split_system_prompt(_load_system_prompt())
    model = policy_call.model_label(profile)

    try:
        body, input_tokens, output_tokens = policy_call.complete(
            ticket, policy, profile, system_prompt, ctx['prompt_text'])
    except policy_call.PolicyRefused as exc:
        raise SafetyFailure(str(exc))
    except policy_call.ProviderFailed as exc:
        logger.warning('AI triage call failed for ticket %s: %s', getattr(ticket, 'ticket_number', ticket.pk), exc)
        return _persist_failed(ticket, requested_by, str(exc)[:500], model)

    body = (body or '').strip()

    # 7. Output content filter.
    ok, reason = output_passes_filter(body)
    if not ok:
        suggestion = _persist_blocked(
            ticket, requested_by, reason, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            raw_body=body,
        )
        record_usage(org, requested_by, input_tokens, output_tokens)
        return suggestion

    # 8. Persist the success row. Triage is advisory only → low risk.
    confidence = Decimal('0.7')
    suggestion = AISuggestion.objects.create(
        organization=org,
        native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
        psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
        kind='triage',
        risk_level='low',
        review_state='draft',
        model_name=model,
        confidence=confidence,
        prompt_version=_prompt_version(),
        suggested_body=body,
        context_snapshot={
            'subject': ctx['subject'],
            'asset': ctx['asset'],
            'kb_hits': ctx['kb_hits'],
            'recent_comment_count': len(ctx['recent_comments']),
            # No secrets, no vault data, no full prompt body — just the
            # shape of what was sent so we can replay/diagnose.
        },
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requested_by=requested_by,
    )
    record_usage(org, requested_by, input_tokens, output_tokens)

    request_path = ''
    if request is not None:
        request_path = getattr(request, 'path', '') or ''
    AuditLog.log(
        user=requested_by, action='ai_triage_generated', organization=org,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'AI triage for {getattr(ticket, "ticket_number", ticket.pk)}',
        description=(
            f'Generated AI triage guidance (model={model}, '
            f'tokens={input_tokens}+{output_tokens})'
        ),
        path=request_path,
        extra_data={
            'model': model, 'prompt_version': _prompt_version(),
            'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'temperature': TRIAGE_TEMPERATURE,
        },
    )
    return suggestion


def _persist_blocked(ticket, user, reason: str, *, model='', input_tokens=0,
                     output_tokens=0, raw_body=''):
    from psa_ai.models import AISuggestion
    from audit.models import AuditLog
    suggestion = AISuggestion.objects.create(
        organization=ticket.organization,
        native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
        psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
        kind='triage',
        review_state='blocked',
        risk_level='low',
        model_name=model or '',
        prompt_version=_prompt_version(),
        suggested_body='',  # never store rejected body content
        context_snapshot={
            'reason': reason,
            'raw_blocked_preview': (raw_body or '')[:400],
        },
        input_tokens=input_tokens, output_tokens=output_tokens,
        requested_by=user,
    )
    AuditLog.log(
        user=user, action='ai_triage_generated', organization=ticket.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'AI triage BLOCKED for {getattr(ticket, "ticket_number", ticket.pk)}',
        description=f'AI triage blocked: {reason}',
        success=False,
        extra_data={'reason': reason},
    )
    return suggestion


def _persist_failed(ticket, user, error: str, model: str):
    from psa_ai.models import AISuggestion
    from audit.models import AuditLog
    suggestion = AISuggestion.objects.create(
        organization=ticket.organization,
        native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
        psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
        kind='triage',
        review_state='failed',
        risk_level='low',
        model_name=model,
        prompt_version=_prompt_version(),
        context_snapshot={'error': error},
        requested_by=user,
    )
    AuditLog.log(
        user=user, action='ai_triage_generated', organization=ticket.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'AI triage FAILED for {getattr(ticket, "ticket_number", ticket.pk)}',
        description=f'AI triage failed: {error[:200]}',
        success=False,
    )
    return suggestion
