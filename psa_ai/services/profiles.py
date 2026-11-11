"""
Which model profiles a technician may use on a customer's ticket, which
paired RMM processes the job, and what it will cost.

A profile is usable only when every one of these holds:
  * the profile is enabled and has a credential (Ollama needs a base URL);
  * the customer's AIBusinessPolicy lists it — or it is the acting
    technician's own key and the policy allows technicians' keys;
  * its credential may be spent here — a company key on that company only,
    an MSP key on customers it is assigned to, a technician key by that
    technician and only where the policy allows technician keys;
  * under a local-only policy, it is an approved on-premises Ollama profile
    and the processor is marked on-premises too.

`availability()` explains every refusal in plain words for the UI. The same
rules run again inside the gateway before any provider is called.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from django.utils import timezone

CHARS_PER_TOKEN = 4
EXCLUDED_MESSAGE = 'This customer is excluded from AI features.'
PROMPT_OVERHEAD_TOKENS = 900  # system prompt + schema


def policy_for(organization):
    from psa_ai.models import AIBusinessPolicy
    return AIBusinessPolicy.objects.filter(organization=organization).first()


def processor_for(organization):
    """The customer's paired RMM, or None. Pairing = an active RMM connection
    of any provider in that organization, approved, with integration secrets
    and a pinned tenant (integrations/ticket_rmm.py)."""
    from integrations.ticket_rmm import processor_for as _processor_for
    return _processor_for(organization)


def processor_is_local(connection) -> bool:
    from integrations.ticket_rmm import settings
    return settings(connection)['location'] == 'local'


def profile_refusal(profile, organization, actor, policy=None, processor=None) -> str:
    """'' if `actor` may use `profile` on `organization`'s tickets, else why not."""
    from psa_ai.models import AIModelProfile
    policy = policy if policy is not None else policy_for(organization)
    if not profile.enabled:
        return f'{profile.name} is disabled.'
    own_key = (profile.credential_owner == AIModelProfile.OWNER_TECHNICIAN
               and profile.owner_user_id == getattr(actor, 'pk', None))
    if profile.credential_owner == AIModelProfile.OWNER_TECHNICIAN and not own_key:
        return f"{profile.name} uses another technician's key."
    if policy is None:
        return f"{profile.name} is not allowed by this customer's AI policy."
    if policy.ai_excluded:
        return EXCLUDED_MESSAGE
    if own_key:
        # A technician's own key is allowed wherever the customer allows
        # technicians' keys; it doesn't need listing profile by profile.
        if not policy.allow_technician_credentials:
            return "This customer doesn't allow technicians' own keys."
    elif not policy.allowed_profiles.filter(pk=profile.pk).exists():
        return f"{profile.name} is not allowed by this customer's AI policy."
    if profile.provider == 'ollama':
        if not profile.base_url:
            return f'{profile.name} has no Ollama address.'
        from psa_ai.services.gateway import origin
        if not profile.approved_destination or origin(profile.base_url) != profile.approved_destination:
            return f"{profile.name}'s Ollama address has not been approved."
    elif not profile.sealed_api_key:
        return f'{profile.name} has no API key.'
    owner = profile.credential_owner
    if owner == AIModelProfile.OWNER_COMPANY and profile.owner_organization_id != organization.pk:
        return f"{profile.name} uses another company's key."
    if owner == AIModelProfile.OWNER_MSP and not profile.assigned_organizations.filter(pk=organization.pk).exists():
        return f"{profile.name}'s MSP key is not assigned to this customer."
    if owner == AIModelProfile.OWNER_TECHNICIAN:
        if profile.owner_user_id != getattr(actor, 'pk', None):
            return f"{profile.name} uses another technician's key."
        if not policy.allow_technician_credentials:
            return "This customer doesn't allow technicians' own keys."
    if policy.local_only:
        if profile.location != AIModelProfile.LOCATION_LOCAL or not profile.local_approved:
            return f'{profile.name} is not an approved on-premises model, and this customer requires one.'
        if processor is not None and not processor_is_local(processor):
            return 'This customer requires on-premises processing, and its paired RMM is not marked on-premises.'
    return ''


def usable_profiles(organization, actor) -> List:
    from psa_ai.models import AIModelProfile
    policy = policy_for(organization)
    if policy is None or policy.ai_excluded:
        return []
    processor = processor_for(organization)
    return [p for p in AIModelProfile.objects.filter(enabled=True).order_by('name')
            if not profile_refusal(p, organization, actor, policy, processor)]


def default_profile(organization, actor):
    """One economical model: the policy's default, else the first usable
    profile marked economical, else the first usable one."""
    usable = usable_profiles(organization, actor)
    if not usable:
        return None
    policy = policy_for(organization)
    if policy and policy.default_profile_id:
        for p in usable:
            if p.pk == policy.default_profile_id:
                return p
    return next((p for p in usable if p.economical), usable[0])


def availability(ticket, actor, mode: str) -> Tuple[bool, List[str]]:
    """Whether `mode` ('analyze' or 'compare') can run on this ticket now."""
    from core.ai_gate import ai_features_enabled
    from psa.feature_flags import is_psa_enabled_for_client
    from psa_ai.permissions import has_capability
    org = ticket.organization
    reasons = []
    if not is_psa_enabled_for_client(org):
        reasons.append('PSA is not enabled for this customer.')
    if not ai_features_enabled():
        reasons.append('AI features are turned off in Settings.')
    if not has_capability(actor, org, mode):
        reasons.append("Your role doesn't include this." if mode == 'analyze'
                       else "Your role doesn't include comparing models.")
    policy = policy_for(org)
    if policy is not None and policy.ai_excluded:
        reasons.append(EXCLUDED_MESSAGE)
    elif policy is None or not policy.analysis_enabled:
        reasons.append("This customer's AI policy doesn't allow ticket analysis.")
    elif mode == 'compare' and not policy.compare_enabled:
        reasons.append("This customer's AI policy doesn't allow model comparison.")
    processor = processor_for(org)
    if processor is None:
        reasons.append('No RMM is paired for analysis at this customer.')
    elif policy is not None and policy.local_only and not processor_is_local(processor):
        reasons.append('This customer requires on-premises processing, and its paired RMM is not marked on-premises.')
    usable = usable_profiles(org, actor) if not reasons else []
    if not reasons and not usable:
        reasons.append('No AI model profile is enabled and allowed for this customer.'
                       + (' You can add your own key under My Profile → My AI keys.'
                          if policy.allow_technician_credentials and not policy.local_only else ''))
    if not reasons and mode == 'compare' and len(usable) < 2:
        reasons.append('Comparing needs at least two allowed model profiles.')
    return (not reasons), reasons


def estimate(profile, evidence_chars: int) -> Tuple[int, int, int]:
    """(input tokens, output tokens, cost in 1/100 cent), worst case."""
    tokens_in = PROMPT_OVERHEAD_TOKENS + evidence_chars // CHARS_PER_TOKEN
    tokens_out = profile.max_output_tokens
    cost = (tokens_in * profile.input_price_per_1k + tokens_out * profile.output_price_per_1k + 999) // 1000
    return tokens_in, tokens_out, cost


def actual_cost(profile, tokens_in: int, tokens_out: int) -> int:
    return (tokens_in * profile.input_price_per_1k + tokens_out * profile.output_price_per_1k + 999) // 1000


def budget_remaining(organization) -> Optional[int]:
    """Today's remaining spend in 1/100 cent, or None without a policy."""
    from psa_ai.models import AIBudgetDay
    policy = policy_for(organization)
    if policy is None:
        return None
    row = AIBudgetDay.objects.filter(organization=organization, day=timezone.localdate()).first()
    used = (row.reserved + row.spent) if row else 0
    return max(0, policy.daily_budget_cents * 100 - used)
