"""
The one place that answers "are the AI features switched on?".

`SystemSetting.psa_ai_enabled` is the master switch, and project convention
(CLAUDE.md) is that every AI-assisted feature is gated by it. Before
v3.17.569 six endpoints never consulted it — the documentation assistant's
generate / enhance / validate / assistant views, asset AI documentation, and
floor-plan generation — so turning AI off in Settings left them working and
still spending against the configured provider.

Three copies of the check had grown up independently (`psa_ai.views._ai_on`,
`security_alerts.ai_summarizer.is_ai_enabled`, `docs.views._docs_ai_ready`).
They all read the same flag, so they now delegate here rather than drift.
"""
from __future__ import annotations

import logging
from functools import wraps

from django.http import JsonResponse

logger = logging.getLogger('core.ai_gate')

AI_DISABLED_MESSAGE = (
    'AI features are turned off. Enable them in Settings → PSA (AI).'
)


def ai_features_enabled() -> bool:
    """True when the master AI switch is on.

    Defaults to off if the settings row cannot be read: an install whose
    settings are unavailable should not be quietly calling a paid provider.
    """
    from core.models import SystemSetting

    try:
        return bool(getattr(SystemSetting.get_settings(), 'psa_ai_enabled', False))
    except Exception:
        logger.warning('Could not read SystemSetting; treating AI as disabled')
        return False


def require_ai_enabled_json(view_fn):
    """Refuse a JSON/AJAX AI endpoint when the master switch is off.

    The shape matches what these endpoints already return on a
    provider-not-configured refusal, so their callers need no changes.
    """
    @wraps(view_fn)
    def _wrapped(request, *args, **kwargs):
        if not ai_features_enabled():
            return JsonResponse(
                {'success': False, 'error': AI_DISABLED_MESSAGE}, status=400,
            )
        return view_fn(request, *args, **kwargs)
    return _wrapped
