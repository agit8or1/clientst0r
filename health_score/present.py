"""Shape a stored snapshot for one viewer: hide the signals they may not see
(money and margin need their own permissions) and recompute every dimension,
the overall score and the coverage from what remains, so a hidden signal
cannot be inferred from a headline number."""
from __future__ import annotations

from . import permissions, registry, scoring
from .models import HealthScoreConfig
from .registry import SCORED

STATUS_BADGE = {'ok': 'success', 'warn': 'warning', 'critical': 'danger',
                'unknown': 'secondary', 'stale': 'secondary'}
STATUS_LABEL = {'ok': 'Healthy', 'warn': 'Needs attention', 'critical': 'At risk',
                'unknown': 'Unknown', 'stale': 'Stale'}


def restrict(dimensions, config, hidden_requires):
    """Copy of a stored `dimensions` mapping without the signals needing a
    hidden permission; dimensions left with no visible signal are dropped.
    Dimension values are recomputed from the visible signals."""
    out = {}
    for key, d in (dimensions or {}).items():
        signals = [s for s in d.get('signals', []) if s.get('requires', '') not in hidden_requires]
        if d.get('signals') and not signals:
            continue
        d = dict(d, signals=signals)
        if hidden_requires:
            active = [s for s in signals if s.get('weight', 1) > 0]
            scored = [s for s in active if s['status'] in SCORED and s.get('value') is not None]
            value = scoring._weighted([(s['value'], s['weight']) for s in scored])
            d['value'] = round(value, 1) if value is not None else None
            d['status'] = (config.status_for(d['value']) if value is not None else
                           'stale' if any(s['status'] == 'stale' for s in active) else 'unknown')
            d['signals_scored'], d['signals_total'] = len(scored), len(active)
        out[key] = d
    return out


def present(snapshot, user, client=None):
    client = client or snapshot.client
    config = HealthScoreConfig.for_client(client)
    hidden = permissions.hidden_requirements(user, client)
    dims = restrict(snapshot.dimensions, config, hidden)
    overall, status, known, total = scoring.overall_from(dims, config)
    rows = []
    for key in registry.DIMENSION_KEYS:
        if key not in dims:
            continue
        d = dict(dims[key])
        d['badge'] = STATUS_BADGE.get(d['status'], 'secondary')
        d['status_label'] = STATUS_LABEL.get(d['status'], d['status'])
        d['signals'] = [dict(s, badge=STATUS_BADGE.get(s['status'], 'secondary'),
                             status_label=STATUS_LABEL.get(s['status'], s['status']))
                        for s in d.get('signals', [])]
        rows.append(d)
    previous = scoring.previous_snapshot(snapshot)
    changes = scoring.explain_change(snapshot, previous, exclude_requires=hidden)
    prev_overall = None
    if previous is not None:
        prev_overall = scoring.overall_from(restrict(previous.dimensions, config, hidden), config)[0]
    return {
        'snapshot': snapshot, 'client': client, 'overall': overall, 'status': status,
        'badge': STATUS_BADGE.get(status, 'secondary'), 'status_label': STATUS_LABEL.get(status, status),
        'known': known, 'total': total,
        'coverage_pct': round(100 * known / total) if total else 0,
        'dimensions': rows, 'hidden': sorted(hidden), 'changes': changes,
        'previous': previous, 'previous_overall': prev_overall,
        'overall_delta': (round(overall - prev_overall, 1)
                          if overall is not None and prev_overall is not None else None),
        'config': config,
    }
