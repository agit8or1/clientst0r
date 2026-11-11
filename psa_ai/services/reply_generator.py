"""
Generate a client-facing reply suggestion for a PSA ticket.

The model, its key, the budget and the sharing rules all come from the
customer's AI policy (services/policy_call.py, security finding S2); the
call goes through the AI gateway like every other ticket AI feature. The
install-wide ANTHROPIC_API_KEY is not used.

Returns either a populated AISuggestion(saved=True) OR a SafetyFailure
exception with the reason. Never raises bare exceptions to the caller —
all infrastructure failures land as a `failed` AISuggestion so the UI
shows a retry button instead of a 500.
"""
from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from pathlib import Path

from django.utils import timezone

from .guardrails import (
    output_passes_filter, quota_exceeded, record_usage,
    subject_is_blocked, user_rate_exceeded,
)
from .context_builder import build_ticket_context
from . import policy_call

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover — graceful when SDK isn't installed
    Anthropic = None


logger = logging.getLogger('psa_ai.reply_generator')

PROMPTS_DIR = Path(__file__).resolve().parent.parent / 'prompts'
SYSTEM_PROMPT_PATH = PROMPTS_DIR / 'system_reply.md'


def _prompt_version():
    """File name + content hash of the system prompt (services/prompt_versions.py)."""
    from .prompt_versions import prompt_version
    return prompt_version(SYSTEM_PROMPT_PATH.name)


class SafetyFailure(Exception):
    """Raised before any model call when a guardrail trips."""


def _load_system_prompt(voice: str, brand: str) -> str:
    text = SYSTEM_PROMPT_PATH.read_text()
    text = text.replace('{{voice}}', voice or 'Professional, concise, confident.')
    text = text.replace('{{brand}}', brand or 'our team')
    return text


def _system_setting():
    from core.models import SystemSetting
    return SystemSetting.get_settings()


def _resolve_api_key():
    """Deprecated: ticket AI no longer uses the install-wide key (security
    finding S2). Kept so older imports keep working; nothing here calls it."""
    return os.getenv('ANTHROPIC_API_KEY', '').strip()


def _resolve_model():
    return os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-6').strip()


def prepare_policy_call(ticket, user):
    """(policy, profile) under the customer's AI policy, or SafetyFailure."""
    try:
        return policy_call.prepare(ticket, user)
    except policy_call.PolicyRefused as exc:
        raise SafetyFailure(str(exc))


def split_system_prompt(text: str) -> str:
    """The prompt files end with a {{context}} slot; the context now goes in
    the user message (wrapped as untrusted), so the slot is pointed there."""
    return text.replace('{{context}}', '(The ticket context is in the user message.)').strip()


def generate_reply_for_ticket(ticket, *, user, request_path: str = '') -> 'AISuggestion':
    """
    Run the full guardrails-and-generate pipeline. Always persists an
    `AISuggestion` row (success, failure, or blocked). Returns it.
    """
    from psa_ai.models import AISuggestion
    from audit.models import AuditLog

    ss = _system_setting()
    org = ticket.organization

    # 0. Master switch.
    if not ss.psa_ai_enabled:
        raise SafetyFailure('PSA AI Assist is disabled in Settings.')

    # 1. Subject blocklist.
    blocked, reason = subject_is_blocked(ticket.subject or '', ss.psa_ai_blocked_subject_keywords or '')
    if blocked:
        return _persist_blocked(ticket, user, reason)

    # 2. Per-user rate limit.
    over, reason = user_rate_exceeded(user, int(ss.psa_ai_per_user_rate_per_min or 0))
    if over:
        raise SafetyFailure(reason)

    # 3. Daily quota check (estimate worst-case 4k input + 2k output).
    over, reason = quota_exceeded(
        org, user, est_tokens=6000,
        org_limit=int(ss.psa_ai_daily_token_limit or 0),
        user_limit=int(ss.psa_ai_per_user_daily_limit or 0),
    )
    if over:
        raise SafetyFailure(reason)

    # 4. The customer's AI policy picks the model and its key (never an
    # install-wide key) and its sharing rules shape the context.
    policy, profile = prepare_policy_call(ticket, user)
    ctx = build_ticket_context(ticket, policy=policy)

    # 5. Call the model through the AI gateway, against the customer's budget.
    system_prompt = split_system_prompt(_load_system_prompt(
        voice=ss.psa_ai_voice or '',
        brand=ss.custom_company_name or ss.site_name or 'our team',
    ))
    model = policy_call.model_label(profile)
    try:
        content_text, input_tokens, output_tokens = policy_call.complete(
            ticket, policy, profile, system_prompt, ctx['prompt_text'])
    except policy_call.PolicyRefused as exc:
        raise SafetyFailure(str(exc))
    except policy_call.ProviderFailed as exc:
        logger.warning('AI reply call failed for ticket %s: %s', getattr(ticket, 'ticket_number', ticket.pk), exc)
        return _persist_failed(ticket, user, str(exc)[:500], model)

    # 7. Parse JSON reply. Be defensive — model occasionally wraps in code fences.
    body, confidence, risk_level = _parse_json_response(content_text)

    # 8. Output content filter.
    ok, reason = output_passes_filter(body)
    if not ok:
        suggestion = _persist_blocked(ticket, user, reason, model=model,
                                      input_tokens=input_tokens, output_tokens=output_tokens,
                                      raw_body=body)
        record_usage(org, user, input_tokens, output_tokens)
        return suggestion

    # 9. Persist the success row.
    suggestion = AISuggestion.objects.create(
        organization=org,
        native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
        psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
        kind='reply',
        risk_level=risk_level,
        review_state='draft',
        model_name=model,
        confidence=Decimal(str(confidence)),
        prompt_version=_prompt_version(),
        suggested_body=body,
        context_snapshot={
            'subject': ctx['subject'],
            'asset': ctx['asset'],
            'kb_hits': ctx['kb_hits'],
            'recent_comment_count': len(ctx['recent_comments']),
        },
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requested_by=user,
    )
    record_usage(org, user, input_tokens, output_tokens)

    AuditLog.log(
        user=user, action='create', organization=org,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'AI reply for {getattr(ticket, "ticket_number", ticket.pk)}',
        description=f'Generated AI reply suggestion (model={model}, confidence={confidence}, risk={risk_level})',
        path=request_path,
        extra_data={
            'model': model, 'prompt_version': _prompt_version(),
            'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'risk_level': risk_level,
        },
    )
    return suggestion


def _parse_json_response(text: str):
    """
    Extract {body, confidence, risk_level} from the model output. The
    system prompt asks for raw JSON, but be tolerant of code fences
    (``` ```json {…}``` ``` ```).
    """
    import re
    if not text:
        return '', 0.0, 'high'
    s = text.strip()
    # Strip code fences if present.
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```$', s, re.S | re.I)
    if fence:
        s = fence.group(1)
    try:
        data = json.loads(s)
    except Exception:
        # Fallback: use the whole text as the body, mark unknown.
        return s[:4000], 0.5, 'medium'
    body = (data.get('body') or '').strip()
    try:
        conf = float(data.get('confidence', 0.0) or 0.0)
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.0
    risk = (data.get('risk_level') or 'medium').lower()
    if risk not in ('low', 'medium', 'high'):
        risk = 'medium'
    return body, conf, risk


def _persist_blocked(ticket, user, reason: str, model='', input_tokens=0,
                     output_tokens=0, raw_body=''):
    from psa_ai.models import AISuggestion
    from audit.models import AuditLog
    suggestion = AISuggestion.objects.create(
        organization=ticket.organization,
        native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
        psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
        kind='reply',
        review_state='blocked',
        model_name=model or '',
        prompt_version=_prompt_version(),
        suggested_body='',  # never store raw rejected body
        context_snapshot={'reason': reason, 'raw_blocked_preview': (raw_body or '')[:400]},
        input_tokens=input_tokens, output_tokens=output_tokens,
        requested_by=user,
    )
    AuditLog.log(
        user=user, action='create', organization=ticket.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'AI reply BLOCKED for {getattr(ticket, "ticket_number", ticket.pk)}',
        description=f'AI reply blocked: {reason}',
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
        kind='reply',
        review_state='failed',
        model_name=model,
        prompt_version=_prompt_version(),
        context_snapshot={'error': error},
        requested_by=user,
    )
    AuditLog.log(
        user=user, action='create', organization=ticket.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'AI reply FAILED for {getattr(ticket, "ticket_number", ticket.pk)}',
        description=f'AI reply failed: {error[:200]}',
        success=False,
    )
    return suggestion
