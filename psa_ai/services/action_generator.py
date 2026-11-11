"""
Generate AI Suggested Actions for a ticket. Each suggestion lands as
its own AISuggestion(kind='action') row so the existing UI / approval
flow can act on each one independently.

Same guardrails as reply_generator: subject blocklist, per-user rate
limit, daily token quota, output content filter, action-type
allowlist, payload re-validation by the dispatcher (action_applier).
"""
from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from pathlib import Path

from django.utils import timezone

from .context_builder import build_ticket_context
from .guardrails import (
    ALLOWED_ACTION_TYPES, action_type_is_allowed,
    output_passes_filter, quota_exceeded, record_usage,
    subject_is_blocked, user_rate_exceeded,
)
from . import policy_call
from .reply_generator import SafetyFailure, prepare_policy_call, split_system_prompt


logger = logging.getLogger('psa_ai.action_generator')

PROMPTS_DIR = Path(__file__).resolve().parent.parent / 'prompts'
SYSTEM_PROMPT_PATH = PROMPTS_DIR / 'system_action.md'


def _prompt_version():
    """File name + content hash of the system prompt (services/prompt_versions.py)."""
    from .prompt_versions import prompt_version
    return prompt_version(SYSTEM_PROMPT_PATH.name)


def _load_system_prompt(*, voice: str, brand: str, status_slugs, priority_codes,
                        assignee_usernames, kb_slugs) -> str:
    text = SYSTEM_PROMPT_PATH.read_text()
    text = text.replace('{{voice}}', voice or 'Professional, concise, confident.')
    text = text.replace('{{brand}}', brand or 'our team')
    text = text.replace('{{available_status_slugs}}', ', '.join(status_slugs) or '—')
    text = text.replace('{{available_priority_codes}}', ', '.join(priority_codes) or '—')
    text = text.replace('{{available_assignee_usernames}}', ', '.join(assignee_usernames) or '—')
    text = text.replace('{{available_kb_slugs}}', ', '.join(kb_slugs) or '—')
    return text


def _gather_choice_lists(ticket):
    """Pull the constrained option lists into the prompt so the model can't
    invent identifiers. We list the slugs / codes / usernames it MAY pick
    from. Anything else gets dropped at parse time."""
    from psa.models import TicketStatus, TicketPriority
    from django.contrib.auth import get_user_model
    User = get_user_model()
    org = ticket.organization

    status_slugs = list(TicketStatus.objects.values_list('slug', flat=True))
    priority_codes = list(TicketPriority.objects.values_list('code', flat=True))

    # Assignees: any active user who is a member of the ticket's org
    # (staff/superusers excluded — they're not in the org membership table).
    try:
        from accounts.models import Membership
        assignee_usernames = list(
            Membership.objects.filter(
                organization=org, is_active=True,
                user__is_active=True,
            ).values_list('user__username', flat=True).distinct()
        )
    except Exception:
        assignee_usernames = []

    kb_slugs = []
    try:
        from docs.models import Document
        from django.db.models import Q
        kb_slugs = list(
            Document.objects.filter(
                Q(organization=org) | Q(is_global=True),
            ).values_list('slug', flat=True)[:30]
        )
    except Exception:
        pass

    return status_slugs, priority_codes, assignee_usernames, kb_slugs


def generate_actions_for_ticket(ticket, *, user, request_path: str = ''):
    """Generate up to N action suggestions; persist each as its own
    AISuggestion(kind='action'). Returns the list."""
    from core.models import SystemSetting
    from audit.models import AuditLog
    from psa_ai.models import AISuggestion

    ss = SystemSetting.get_settings()
    org = ticket.organization

    if not ss.psa_ai_enabled:
        raise SafetyFailure('PSA AI Assist is disabled in Settings.')

    blocked, reason = subject_is_blocked(
        ticket.subject or '', ss.psa_ai_blocked_subject_keywords or '')
    if blocked:
        suggestion = AISuggestion.objects.create(
            organization=org,
            native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
            psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
            kind='action', review_state='blocked',
            model_name='', prompt_version=_prompt_version(),
            context_snapshot={'reason': reason}, requested_by=user,
        )
        AuditLog.log(
            user=user, action='create', organization=org,
            object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
            object_repr=f'AI actions BLOCKED for {getattr(ticket, "ticket_number", ticket.pk)}',
            description=f'AI actions blocked: {reason}',
            success=False, extra_data={'reason': reason},
        )
        return [suggestion]

    over, reason = user_rate_exceeded(user, int(ss.psa_ai_per_user_rate_per_min or 0))
    if over:
        raise SafetyFailure(reason)
    over, reason = quota_exceeded(
        org, user, est_tokens=6000,
        org_limit=int(ss.psa_ai_daily_token_limit or 0),
        user_limit=int(ss.psa_ai_per_user_daily_limit or 0),
    )
    if over:
        raise SafetyFailure(reason)

    # The customer's AI policy picks the model and key (never the
    # install-wide key) and its sharing rules shape the context (S2).
    policy, profile = prepare_policy_call(ticket, user)
    ctx = build_ticket_context(ticket, policy=policy)
    status_slugs, priority_codes, assignee_usernames, kb_slugs = _gather_choice_lists(ticket)
    system_prompt = split_system_prompt(_load_system_prompt(
        voice=ss.psa_ai_voice or '',
        brand=ss.custom_company_name or ss.site_name or 'our team',
        status_slugs=status_slugs, priority_codes=priority_codes,
        assignee_usernames=assignee_usernames, kb_slugs=kb_slugs,
    ))
    model = policy_call.model_label(profile)

    try:
        text, in_tokens, out_tokens = policy_call.complete(ticket, policy, profile, system_prompt,
                                                           ctx['prompt_text'])
    except policy_call.PolicyRefused as exc:
        raise SafetyFailure(str(exc))
    except policy_call.ProviderFailed as exc:
        logger.warning('Action generation failed for ticket %s: %s', getattr(ticket, 'ticket_number', ticket.pk),
                       exc)
        suggestion = AISuggestion.objects.create(
            organization=org,
            native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
            psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
            kind='action', review_state='failed',
            model_name=model, prompt_version=_prompt_version(),
            context_snapshot={'error': str(exc)[:500]},
            requested_by=user,
        )
        return [suggestion]

    actions, top_conf = _parse_actions(text)

    record_usage(org, user, in_tokens, out_tokens)

    # Output content filter on each rationale + payload.
    saved = []
    for a in actions:
        action_type = a.get('action_type', '')
        ok_type, _ = action_type_is_allowed(action_type)
        if not ok_type:
            continue
        # Run output filter on the rationale + payload string form.
        joined = (a.get('rationale', '') or '') + ' ' + json.dumps(a.get('payload') or {})
        ok, reason = output_passes_filter(joined)
        review_state = 'draft' if ok else 'blocked'
        s = AISuggestion.objects.create(
            organization=org,
            native_ticket=ticket if ticket.__class__.__name__ == 'Ticket' else None,
            psa_ticket=ticket if ticket.__class__.__name__ == 'PSATicket' else None,
            kind='action',
            risk_level=a.get('risk_level', 'medium'),
            review_state=review_state,
            model_name=model,
            confidence=Decimal(str(top_conf)),
            prompt_version=_prompt_version(),
            action_type=action_type,
            action_payload=a.get('payload') or {},
            suggested_body=a.get('rationale', '')[:500],
            input_tokens=in_tokens // max(1, len(actions)),
            output_tokens=out_tokens // max(1, len(actions)),
            context_snapshot={'reason': reason} if not ok else {},
            requested_by=user,
        )
        saved.append(s)
        AuditLog.log(
            user=user, action='create', organization=org,
            object_type='psa_ai.AISuggestion', object_id=s.pk,
            object_repr=f'AI action {action_type}',
            description=f'Generated AI action {action_type} for {getattr(ticket, "ticket_number", ticket.pk)}',
            path=request_path,
            extra_data={'action_type': action_type, 'risk_level': s.risk_level,
                        'review_state': review_state},
        )
    return saved


def _parse_actions(text: str):
    """Pull JSON {confidence, actions: [...]} out of model output. Tolerant
    of code-fence wrapping. Returns ([action_dicts], overall_confidence)."""
    import re
    if not text:
        return [], 0.0
    s = text.strip()
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```$', s, re.S | re.I)
    if fence:
        s = fence.group(1)
    try:
        data = json.loads(s)
    except Exception:
        return [], 0.0
    actions = data.get('actions') or []
    if not isinstance(actions, list):
        return [], 0.0
    try:
        conf = float(data.get('confidence', 0.0) or 0.0)
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.0
    cleaned = []
    for a in actions[:6]:  # cap suggestions to 6 just in case
        if isinstance(a, dict) and 'action_type' in a:
            cleaned.append(a)
    return cleaned, conf
