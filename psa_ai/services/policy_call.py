"""
One model call for the older ticket AI features (reply drafts, suggested
actions, triage guidance), under the customer's AI policy.

Before v3.17.66x these called Anthropic directly with the install-wide
ANTHROPIC_API_KEY and never consulted the customer's AIBusinessPolicy
(security finding S2). They now take the same path as "Analyze ticket" and
AI Troubleshoot:

  * the customer must have an AI policy with analysis switched on and must
    not be excluded (ai_excluded);
  * the model is the policy's usable default profile
    (profiles.default_profile → profile_refusal: enabled, allowed by the
    policy, credential owner, local-only), never an install-wide key;
  * the ticket context is built under the customer's sharing rules
    (context_builder with the policy; ticket text withheld → refused);
  * the worst-case cost is reserved against the daily and monthly ceilings
    (budget.reserve) and settled with the actual cost;
  * the provider is called through gateway.call_provider (fixed hosts,
    sealed key, no redirects, size-limited response).

In AI_GATEWAY_MODE=worker the web process cannot open provider keys, so
these synchronous features refuse cleanly and point at "Analyze ticket" /
AI Troubleshoot, which run through the worker.
"""
from __future__ import annotations

from typing import Tuple

from . import budget, gateway, gateway_keys, profiles
from .tenant_rules import EXCLUDED_MESSAGE


class PolicyRefused(Exception):
    """Refused before any model call. Subclassed by reply_generator.SafetyFailure callers."""


class ProviderFailed(Exception):
    pass


def prepare(ticket, user):
    """(policy, profile) for this ticket, or PolicyRefused with the reason."""
    org = ticket.organization
    policy = profiles.policy_for(org)
    if policy is None:
        raise PolicyRefused("This customer has no AI policy, so ticket AI is off for it.")
    if policy.ai_excluded:
        raise PolicyRefused(EXCLUDED_MESSAGE)
    if not policy.analysis_enabled:
        raise PolicyRefused("This customer's AI policy doesn't allow ticket AI.")
    if not policy.share_ticket_text:
        raise PolicyRefused("This customer's sharing rules withhold ticket text from AI.")
    if gateway_keys.mode() == 'worker':
        raise PolicyRefused('This feature needs the in-process AI gateway. Use "Analyze ticket" or '
                            'AI Troubleshoot, which run through the AI gateway worker.')
    profile = profiles.default_profile(org, user)
    if profile is None:
        raise PolicyRefused('No AI model profile is enabled and allowed for this customer.')
    return policy, profile


def model_label(profile) -> str:
    return f'{profile.provider}/{profile.model}'[:100]


def complete(ticket, policy, profile, system: str, user_text: str) -> Tuple[str, int, int]:
    """(text, input tokens, output tokens). PolicyRefused when the budget
    has no room; ProviderFailed when the call failed (reservation released)."""
    org = ticket.organization
    _, _, cost = profiles.estimate(profile, len(system) + len(user_text))
    if cost and not budget.reserve(org, cost, policy.daily_budget_cents * 100):
        raise PolicyRefused("This customer's AI budget doesn't cover this request.")
    try:
        text, t_in, t_out = gateway.call_provider(profile, system, user_text)
    except gateway.GatewayRefusal as e:
        budget.release(org, cost)
        raise ProviderFailed(e.message)
    except gateway.BlockedDestinationError:
        budget.release(org, cost)
        raise ProviderFailed('The provider address is not an allowed destination.')
    except gateway_keys.GatewayKeyError as e:
        budget.release(org, cost)
        raise ProviderFailed(str(e))
    except Exception as e:  # network errors and the like
        budget.release(org, cost)
        raise ProviderFailed(f'The model call failed ({e.__class__.__name__}).')
    budget.settle(org, cost, profiles.actual_cost(profile, t_in, t_out))
    return text, t_in, t_out
