"""Customer health pages (MSP staff only; /client-health/ is also a
staff-only prefix in accounts.middleware.SectionPermissionMiddleware)."""
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Organization

from . import permissions, present, registry, scoring
from .models import CustomerHealthSnapshot, HealthScoreConfig


def staff_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not permissions.can_use(request):
            raise PermissionDenied('Customer health is for MSP staff.')
        return view(request, *args, **kwargs)
    return wrapped


def _client_or_404(request, client_id):
    client = get_object_or_404(Organization, pk=client_id)
    if not permissions.can_view_client(request, client):
        raise PermissionDenied('You do not have access to this client.')
    return client


def _latest_by_client(ids):
    out = {}
    qs = CustomerHealthSnapshot.objects.filter(client_id__in=ids).order_by('client_id', '-date', '-computed_at')
    for snap in qs:
        out.setdefault(snap.client_id, snap)
    return out


@staff_required
def client_list(request):
    allowed = permissions.client_ids(request)
    clients = Organization.objects.filter(is_active=True).order_by('name')
    if allowed is not None:
        clients = clients.filter(pk__in=allowed)
    clients = list(clients)
    latest = _latest_by_client([c.pk for c in clients])
    flt = request.GET.get('filter', '')
    sort = request.GET.get('sort', 'overall')
    sort = sort if sort in ('overall', 'name', *registry.DIMENSION_KEYS) else 'overall'
    rows = []
    for c in clients:
        snap = latest.get(c.pk)
        if snap is None:
            rows.append({'client': c, 'p': None, 'dims': {}, 'unknown': True, 'stale': False})
            continue
        p = present.present(snap, request.user, c)
        dims = {d['key']: d for d in p['dimensions']}
        rows.append({
            'client': c, 'p': p, 'dims': dims,
            'cells': [dims.get(k) for k in registry.DIMENSION_KEYS],
            'unknown': p['overall'] is None or p['known'] < p['total'],
            'stale': any(d['status'] == 'stale' for d in p['dimensions']),
        })
    if flt == 'unknown':
        rows = [r for r in rows if r['unknown']]
    elif flt == 'stale':
        rows = [r for r in rows if r['stale']]
    elif flt == 'at_risk':
        rows = [r for r in rows if r['p'] and r['p']['status'] in ('critical', 'warn')]

    def key(r):
        if sort == 'name':
            return (r['client'].name.lower(),)
        if sort == 'overall':
            v = r['p']['overall'] if r['p'] else None
        else:
            d = r['dims'].get(sort)
            v = d['value'] if d else None
        # worst first; clients with no value after those that have one
        return (v is None, v if v is not None else 0, r['client'].name.lower())
    rows.sort(key=key)
    return render(request, 'health_score/client_list.html', {
        'rows': rows, 'filter': flt, 'sort': sort, 'dimensions': registry.DIMENSIONS,
        'can_manage': permissions.can_manage_settings(request.user),
    })


@staff_required
def client_detail(request, client_id):
    client = _client_or_404(request, client_id)
    snap = scoring.latest_snapshot(client)
    ctx = {'client': client, 'can_manage': permissions.can_manage_settings(request.user, client),
           'p': present.present(snap, request.user, client) if snap else None}
    return render(request, 'health_score/client_detail.html', ctx)


@staff_required
@require_POST
def recompute(request, client_id):
    client = _client_or_404(request, client_id)
    scoring.compute_and_save(client)
    messages.success(request, f'Health score recomputed for {client.name}.')
    return redirect('health_score:detail', client_id=client.pk)


def _config_for(request):
    """(config row or None, client or None, scope label). `?client=` edits that
    client's override; none edits the install default."""
    cid = request.GET.get('client') or request.POST.get('client')
    client = None
    if cid and str(cid).isdigit():
        client = _client_or_404(request, int(cid))
    return client


@staff_required
def settings_view(request):
    client = _config_for(request)
    if not permissions.can_manage_settings(request.user, client):
        raise PermissionDenied('Changing health score weights needs the manage_health_score_settings permission.')
    row = HealthScoreConfig.objects.filter(organization=client).first()
    effective = row or HealthScoreConfig.for_client(client) if client else (row or HealthScoreConfig())
    if request.method == 'POST':
        if request.POST.get('reset') and row is not None and client is not None:
            row.delete()
            messages.success(request, f'{client.name} uses the default weights again.')
            return redirect(f"{reverse('health_score:settings')}?client={client.pk}")
        errors = []

        def num(name, default, hi=1000):
            raw = (request.POST.get(name) or '').strip()
            if raw == '':
                return default
            try:
                v = float(raw)
            except ValueError:
                errors.append(f'{name}: not a number')
                return default
            if v < 0 or v > hi:
                errors.append(f'{name}: must be between 0 and {hi}')
                return default
            return v
        dim_w = {d: num(f'dim_{d}', registry.DEFAULT_DIMENSION_WEIGHTS[d]) for d in registry.DIMENSION_KEYS}
        sig_w = {s.key: num(f'sig_{s.key}', s.weight) for s in registry.all_signals()}
        ok = int(num('ok_threshold', 75, 100))
        warn = int(num('warn_threshold', 50, 100))
        if warn >= ok:
            errors.append('The at-risk threshold must be below the healthy threshold.')
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            obj = row or HealthScoreConfig(organization=client)
            obj.dimension_weights, obj.signal_weights = dim_w, sig_w
            obj.ok_threshold, obj.warn_threshold = ok, warn
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'Health score weights saved. They apply from the next computation.')
            return redirect(f"{reverse('health_score:settings')}" + (f'?client={client.pk}' if client else ''))
    dims = []
    for key, label in registry.DIMENSIONS:
        dims.append({'key': key, 'label': label, 'weight': effective.dimension_weight(key),
                     'signals': [{'key': s.key, 'label': s.label, 'description': s.description,
                                  'weight': effective.signal_weight(s.key)}
                                 for s in registry.signals_for(key)]})
    return render(request, 'health_score/settings.html', {
        'dims': dims, 'config': effective, 'client': client, 'has_override': row is not None and client is not None})
