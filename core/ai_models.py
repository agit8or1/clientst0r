"""
Claude model choices for Settings → AI, and what each model accepts.

v3.17.596 (issue #149): the dropdown still offered Claude Opus/Sonnet 4.5 as
the newest models plus two retired Claude 3.5 models. The list lives here so
the template, the save path and the tests all read one source.
"""
from __future__ import annotations

import re

# (model id, label). Current generation first.
CURRENT_CLAUDE_MODELS = [
    ('claude-opus-5-5', 'Claude Opus 5.5 (Recommended)'),
    ('claude-sonnet-5-5', 'Claude Sonnet 5.5 (Faster, lower cost)'),
    ('claude-haiku-5-5', 'Claude Haiku 5.5 (Fastest, lowest cost)'),
    ('claude-fable-5-1', 'Claude Fable 5.1 (Most capable, highest cost)'),
]

# Older models that are still served. The 4.5 entries keep their dated IDs
# because that is what earlier releases saved to .env, so an existing choice
# still shows as selected.
PREVIOUS_CLAUDE_MODELS = [
    ('claude-opus-5', 'Claude Opus 5'),
    ('claude-sonnet-5', 'Claude Sonnet 5'),
    ('claude-opus-4-8', 'Claude Opus 4.8'),
    ('claude-sonnet-4-6', 'Claude Sonnet 4.6'),
    ('claude-haiku-4-5', 'Claude Haiku 4.5'),
    ('claude-opus-4-5-20251101', 'Claude Opus 4.5'),
    ('claude-sonnet-4-5-20250929', 'Claude Sonnet 4.5'),
]

CLAUDE_MODEL_IDS = {m for m, _ in CURRENT_CLAUDE_MODELS + PREVIOUS_CLAUDE_MODELS}

# Anything that looks like a model ID. A saved value outside the list (set by
# hand in .env) is kept rather than silently replaced on the next save.
_MODEL_ID_RE = re.compile(r'^claude-[a-z0-9][a-z0-9.@-]{2,80}$')

# Models that still accept temperature / top_p / top_k. Opus 4.7 and later,
# the Sonnet 5 line, Haiku 5.5 and Fable reject non-default sampling values
# with a 400, so anything not listed here gets no sampling parameters.
_SAMPLING_PREFIXES = (
    'claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5',
    'claude-opus-4-5', 'claude-sonnet-4-5', 'claude-opus-4-1',
    'claude-opus-4-0', 'claude-opus-4-2025', 'claude-sonnet-4-0',
    'claude-sonnet-4-2025', 'claude-3',
)


def is_valid_claude_model(model: str) -> bool:
    return bool(model) and (model in CLAUDE_MODEL_IDS or bool(_MODEL_ID_RE.match(model)))


def accepts_sampling_params(model: str) -> bool:
    """True if `temperature` etc. may be sent to this model."""
    return (model or '').startswith(_SAMPLING_PREFIXES)


def sampling_kwargs(model: str, **params) -> dict:
    """`params` (e.g. temperature=0) if the model accepts them, else {}."""
    return dict(params) if accepts_sampling_params(model) else {}
