"""Dimensions and the signal-provider registry.

A signal provider is a function `fn(ctx) -> dict` registered with
`@signal(dimension, key, label)`. Other apps add their own signals by
importing this module and registering one (the module must be imported at
startup, e.g. from the app's `AppConfig.ready`).

The dict a provider returns (build it with `result()`):

  value        0-100 (higher is healthier) or None when there is nothing
               trustworthy to score
  status       ok / warn / critical / unknown / stale. `stale` means the
               data exists but is older than it can be trusted; it is never
               scored and never shown as ok.
  as_of        ISO date-time of the newest evidence (or None)
  source       where the data came from
  refs         contributing records: [{model, pk, label, url}]
  explanation  one sentence a technician can read

Unknown is not healthy: only signals with a value and an ok / warn /
critical status take part in scoring (health_score.scoring).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DIMENSIONS = [
    ('technical', 'Technical'),
    ('security', 'Security'),
    ('backup', 'Backup'),
    ('service_delivery', 'Service delivery'),
    ('commercial', 'Commercial'),
    ('satisfaction', 'Satisfaction'),
]
DIMENSION_LABELS = dict(DIMENSIONS)
DIMENSION_KEYS = [k for k, _l in DIMENSIONS]

DEFAULT_DIMENSION_WEIGHTS = {
    'technical': 20, 'security': 20, 'backup': 15,
    'service_delivery': 20, 'commercial': 15, 'satisfaction': 10,
}

SCORED = ('ok', 'warn', 'critical')
STATUSES = ('ok', 'warn', 'critical', 'unknown', 'stale')

MAX_REFS = 25


@dataclass
class Signal:
    dimension: str
    key: str
    label: str
    fn: Callable
    weight: float = 1.0
    description: str = ''
    requires: str = ''      # '' | 'billing' | 'profitability': extra permission to see it


_SIGNALS: Dict[str, Signal] = {}


def signal(dimension, key, label, weight=1.0, description='', requires=''):
    """Register a signal provider."""
    if dimension not in DIMENSION_LABELS:
        raise ValueError(f'Unknown health dimension {dimension!r}')

    def deco(fn):
        _SIGNALS[key] = Signal(dimension, key, label, fn, weight, description, requires)
        return fn
    return deco


def signals_for(dimension) -> List[Signal]:
    _load_builtin()
    return [s for s in _SIGNALS.values() if s.dimension == dimension]


def all_signals() -> List[Signal]:
    _load_builtin()
    return list(_SIGNALS.values())


def default_signal_weight(key):
    sig = _SIGNALS.get(key)
    return sig.weight if sig else 1.0


def _load_builtin():
    from . import providers  # noqa: F401  (registers the built-in signals)


def ref(obj, label, url=''):
    """A contributing-record reference."""
    return {'model': f'{obj._meta.app_label}.{obj._meta.model_name}', 'pk': obj.pk,
            'label': str(label)[:200], 'url': url or ''}


def result(value=None, status='unknown', as_of=None, source='', refs=None, explanation='', **extra):
    if value is not None:
        value = max(0.0, min(100.0, round(float(value), 1)))
    if status not in STATUSES:
        raise ValueError(status)
    out = {
        'value': value, 'status': status,
        'as_of': as_of.isoformat() if hasattr(as_of, 'isoformat') else as_of,
        'source': source, 'refs': list(refs or [])[:MAX_REFS],
        'explanation': explanation,
    }
    out.update(extra)
    return out


def unknown(explanation, source='', status='unknown', as_of=None, refs=None):
    return result(None, status, as_of, source, refs, explanation)


@dataclass
class Context:
    """What a provider gets: the client organization, "now" and the config
    (for grading a value). Providers filter every query by `client`."""
    client: object
    now: object
    config: object
    today: object = None
    extra: dict = field(default_factory=dict)

    def grade(self, value):
        return self.config.status_for(value)


def run_signal(sig: Signal, ctx: Context) -> dict:
    """Run one provider; a crash or a malformed answer is unknown, never ok."""
    try:
        out = sig.fn(ctx)
        if not isinstance(out, dict) or out.get('status') not in STATUSES:
            raise ValueError('malformed signal result')
        if out['status'] in SCORED and out.get('value') is None:
            out = unknown('The signal produced a status without a value.', status='unknown')
    except Exception:  # noqa: BLE001 - a broken provider must not break the score
        logger.exception('health_score signal %s failed for client %s', sig.key, getattr(ctx.client, 'pk', None))
        out = unknown('This signal could not be computed.')
    out.setdefault('refs', [])
    out.update({'key': sig.key, 'label': sig.label, 'dimension': sig.dimension, 'requires': sig.requires})
    return out
