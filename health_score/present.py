"""Shape a stored snapshot for one viewer: hide what they may not see and
recompute the overall score and coverage from what remains, so a hidden
dimension cannot be inferred from the headline number."""
from __future__ import annotations

from . import permissions, registry, scoring
from .models import HealthScoreConfig

STATUS_BADGE = {'ok': 'success', 'warn': 'warning', 'critical': 'danger',
                'unknown': 'secondary', 'stale': 'secondary'}
STATUS_LABEL = {'ok': 'Healthy', 'warn': 'Needs attention', 'critical': 'At risk',
                'unknown': 'Unknown', 'stale': 'Stale'}


def present(snapshot, user, client=None):
    client = client or snapshot.client
    config = HealthScoreConfig.for_client(client)
    hidden = permissions.hidden_dimensions(user, client)
    dims = snapshot.dimensions or {}
    overall, status, known, total = scoring.overall_from(dims, config, exclude=hidden)
    rows = []
    for key in registry.DIMENSION_KEYS:
        if key in hidden or key not in dims:
            continue
        d = dict(dims[key])
        d['badge'] = STATUS_BADGE.get(d['status'], 'secondary')
        d['status_label'] = STATUS_LABEL.get(d['status'], d['status'])
        d['signals'] = [dict(s, badge=STATUS_BADGE.get(s['status'], 'secondary'),
                             status_label=STATUS_LABEL.get(s['status'], s['status']))
                        for s in d.get('signals', [])]
        rows.append(d)
    previous = scoring.previous_snapshot(snapshot)
    changes = scoring.explain_change(snapshot, previous, exclude=hidden)
    prev_overall = None
    if previous is not None:
        prev_overall = scoring.overall_from(previous.dimensions or {}, config, exclude=hidden)[0]
    return {
        'snapshot': snapshot, 'client': client, 'overall': overall, 'status': status,
        'badge': STATUS_BADGE.get(status, 'secondary'), 'status_label': STATUS_LABEL.get(status, status),
        'known': known, 'total': total,
        'coverage_pct': round(100 * known / total) if total else 0,
        'dimensions': rows, 'hidden': hidden, 'changes': changes,
        'previous': previous, 'previous_overall': prev_overall,
        'overall_delta': (round(overall - prev_overall, 1)
                          if overall is not None and prev_overall is not None else None),
        'config': config,
    }
