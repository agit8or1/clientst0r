"""Computing, storing and explaining customer health.

Rules (Phase 78.5 "unknown is not healthy"):
  * only signals with a value and an ok / warn / critical status are scored;
    unknown and stale signals are listed but carry no weight;
  * a dimension is known when at least one of its signals is scored;
  * the overall score averages only the known dimensions and always comes
    with its coverage ("based on 4 of 6 dimensions"); with no known
    dimension there is no score at all.
"""
from __future__ import annotations

from django.utils import timezone

from . import registry
from .models import CustomerHealthSnapshot, HealthScoreConfig
from .registry import SCORED, Context, run_signal, signals_for


def _weighted(pairs):
    total = sum(w for _v, w in pairs)
    if total <= 0:
        return None
    return sum(v * w for v, w in pairs) / total


def compute_dimension(dimension, ctx, config):
    signals = []
    for sig in signals_for(dimension):
        out = run_signal(sig, ctx)
        out['weight'] = config.signal_weight(sig.key)
        signals.append(out)
    active = [s for s in signals if s['weight'] > 0]
    scored = [s for s in active if s['status'] in SCORED and s['value'] is not None]
    value = _weighted([(s['value'], s['weight']) for s in scored])
    if value is not None:
        value = round(value, 1)
        status = config.status_for(value)
    elif any(s['status'] == 'stale' for s in active):
        status = 'stale'
    else:
        status = 'unknown'
    return {
        'key': dimension, 'label': registry.DIMENSION_LABELS[dimension],
        'weight': config.dimension_weight(dimension),
        'value': value, 'status': status,
        'signals_scored': len(scored), 'signals_total': len(active),
        'signals': signals,
    }


def overall_from(dimensions, config, exclude=()):
    """(overall, status, known, total) from a computed `dimensions` mapping.
    `exclude` removes dimensions (those a viewer may not see) from every
    count, so the figure cannot leak what is hidden."""
    pairs, total = [], 0
    for key, d in dimensions.items():
        if key in exclude or (d.get('weight') or 0) <= 0:
            continue
        total += 1
        if d.get('value') is not None:
            pairs.append((d['value'], d['weight']))
    overall = _weighted(pairs)
    if overall is None:
        return None, 'unknown', 0, total
    overall = round(overall, 1)
    return overall, config.status_for(overall), len(pairs), total


def compute_client(client, now=None, config=None):
    """Compute (without saving) the health of one client organization."""
    now = now or timezone.now()
    config = config or HealthScoreConfig.for_client(client)
    ctx = Context(client=client, now=now, config=config, today=timezone.localdate(now))
    dimensions = {d: compute_dimension(d, ctx, config) for d in registry.DIMENSION_KEYS}
    overall, status, known, total = overall_from(dimensions, config)
    return {'overall': overall, 'status': status, 'known_dimensions': known,
            'total_dimensions': total, 'dimensions': dimensions, 'computed_at': now}


def compute_and_save(client, now=None, config=None):
    """Compute and store today's snapshot for `client` (replacing today's
    earlier one: on-demand recomputes update the day's row)."""
    data = compute_client(client, now, config)
    snap, _created = CustomerHealthSnapshot.objects.update_or_create(
        client=client, date=timezone.localdate(data['computed_at']),
        defaults={'computed_at': data['computed_at'], 'overall': data['overall'], 'status': data['status'],
                  'known_dimensions': data['known_dimensions'],
                  'total_dimensions': data['total_dimensions'], 'dimensions': data['dimensions']})
    return snap


def previous_snapshot(snapshot):
    return (CustomerHealthSnapshot.objects.filter(client_id=snapshot.client_id, date__lt=snapshot.date)
            .order_by('-date').first())


def latest_snapshot(client):
    return CustomerHealthSnapshot.objects.filter(client=client).order_by('-date', '-computed_at').first()


# ------------------------------------------------------------ explanations

def _ref_key(r):
    return (r.get('model'), r.get('pk'))


def explain_change(current, previous, exclude=(), exclude_requires=()):
    """What moved between two snapshots, per signal, with the records that
    appeared or went away. Returns a list ordered by size of the move."""
    if previous is None:
        return []
    out = []
    before_dims = previous.dimensions or {}
    for dkey, dim in (current.dimensions or {}).items():
        if dkey in exclude:
            continue
        before_sigs = {s['key']: s for s in (before_dims.get(dkey) or {}).get('signals', [])}
        for sig in dim.get('signals', []):
            old = before_sigs.get(sig['key'])
            if old is None or sig.get('requires') in exclude_requires:
                continue
            v_new, v_old = sig.get('value'), old.get('value')
            s_new, s_old = sig.get('status'), old.get('status')
            old_refs = {_ref_key(r): r for r in old.get('refs', [])}
            new_refs = {_ref_key(r): r for r in sig.get('refs', [])}
            appeared = [r for k, r in new_refs.items() if k not in old_refs]
            cleared = [r for k, r in old_refs.items() if k not in new_refs]
            if v_new == v_old and s_new == s_old and not appeared and not cleared:
                continue
            delta = None if v_new is None or v_old is None else round(v_new - v_old, 1)
            out.append({
                'dimension': dkey, 'dimension_label': dim.get('label', dkey),
                'key': sig['key'], 'label': sig['label'],
                'before': v_old, 'after': v_new, 'delta': delta,
                'before_status': s_old, 'after_status': s_new,
                'appeared': appeared, 'cleared': cleared,
                'explanation': sig.get('explanation', ''),
                'before_explanation': old.get('explanation', ''),
                'direction': ('worse' if (delta or 0) < -0.05 else 'better' if (delta or 0) > 0.05
                              else 'changed'),
            })
    out.sort(key=lambda c: -abs(c['delta']) if c['delta'] is not None else -1000)
    return out
