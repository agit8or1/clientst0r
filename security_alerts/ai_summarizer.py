"""
Phase 23 v3.17.362 — **OPTIONAL AI** incident summarization.

Given a SecurityIncident, build a short executive summary + suggested
next steps. Gated by `SystemSetting.psa_ai_enabled` — when off, the
function refuses to call any provider and returns a structured
"disabled" sentinel.

Provider integration is intentionally pluggable: the existing
`psa_ai/services/reply_generator.py` Anthropic plumbing can drop in
later by replacing `_provider_call` (look for the same
`_resolve_api_key` + Anthropic client pattern). For this release we
expose a thin abstraction that callers can monkey-patch in tests.
"""
from __future__ import annotations

import logging


logger = logging.getLogger('security_alerts.ai_summarizer')


def is_ai_enabled() -> bool:
    from core.ai_gate import ai_features_enabled
    return ai_features_enabled()


def summarize_incident(incident, *, requested_by=None) -> dict:
    """
    Returns a dict like:
    {
        'ok': bool,
        'enabled': bool,
        'summary': str,
        'next_steps': list[str],
        'reason': str,           # populated when ok=False
    }

    Side effects: appends a `note` event to the incident timeline
    when an AI summary is successfully produced.
    """
    if not is_ai_enabled():
        return {
            'ok': False,
            'enabled': False,
            'summary': '',
            'next_steps': [],
            'reason': 'AI features are disabled in System Settings (psa_ai_enabled=False).',
        }

    try:
        out = _provider_call(incident, requested_by=requested_by)
    except Exception as exc:
        logger.exception('AI summarization failed')
        return {
            'ok': False,
            'enabled': True,
            'summary': '',
            'next_steps': [],
            'reason': f'AI provider error: {exc}',
        }

    summary = (out.get('summary') or '').strip()
    next_steps = list(out.get('next_steps') or [])
    if not summary:
        return {
            'ok': False,
            'enabled': True,
            'summary': '',
            'next_steps': next_steps,
            'reason': 'AI provider returned empty summary.',
        }

    # Persist as a timeline note (kind='note', actor=requested_by).
    try:
        incident.add_event(
            kind='note',
            message=f'AI summary: {summary}',
            user=requested_by,
        )
    except Exception:
        pass

    return {
        'ok': True,
        'enabled': True,
        'summary': summary,
        'next_steps': next_steps,
        'reason': '',
    }


def _provider_call(incident, *, requested_by=None) -> dict:
    """Default provider call — heuristic stub.

    Production deployments should override this by calling
    `set_provider(callable)` with a function that uses the existing
    `psa_ai` Anthropic plumbing. The stub is deterministic so tests
    don't need network.
    """
    if _OVERRIDE_PROVIDER is not None:
        return _OVERRIDE_PROVIDER(incident, requested_by=requested_by)

    # Heuristic fallback that summarizes the incident's own attributes.
    severity = incident.severity
    title = incident.title
    asset = incident.asset_hint or '(unspecified asset)'
    n_alerts = incident.alerts.count()

    summary = (
        f'{severity.upper()} severity incident on {asset}: "{title}". '
        f'Aggregated {n_alerts} related alert{"s" if n_alerts != 1 else ""} '
        f'so far; status is {incident.status}.'
    )
    steps = [
        f'Verify the affected asset {asset} is under active investigation.',
        'Cross-reference the alerts in the incident timeline against the latest threat intel feed.',
        'If contained, document remediation actions and move the incident to "resolved".',
    ]
    return {'summary': summary, 'next_steps': steps}


_OVERRIDE_PROVIDER = None


def set_provider(callable_or_none):
    """Allow tests / production deployments to override the provider."""
    global _OVERRIDE_PROVIDER
    _OVERRIDE_PROVIDER = callable_or_none
