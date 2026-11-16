"""Business Overview pages.

  overview   the page: filter bar plus one empty card per metric the viewer's
             role covers; each card loads itself from `metric`
  metric     one card as JSON (cached per viewer scope and filters)
  records    the records behind one card: an HTML list, or JSON with
             ?format=json

All three are MSP staff only (the /reports/ prefix is staff-only in
SectionPermissionMiddleware, and each view checks again) and need
reports_view_dashboards across customers; each card then needs its own
permission, scoped per customer (executive.metrics.Scope).
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_GET

from reports.access import require_msp_wide_perm

from . import metrics, providers


def _staff_only(request):
    from psa.visibility import is_msp_staff
    if not is_msp_staff(request.user):
        raise PermissionDenied('The Business Overview is available to MSP staff only.')


def _visible(user):
    """(provider, scope) for every metric the user's role covers."""
    out = []
    for p in providers.PROVIDERS:
        scope = metrics.Scope.for_user(user, p.permission_key())
        if not scope.empty:
            out.append((p, scope))
    return out


def _provider_or_404(user, key):
    p = providers.get(key)
    if p is None:
        raise Http404('No such metric.')
    if metrics.Scope.for_user(user, p.permission_key()).empty:
        raise PermissionDenied('Your role does not include this metric.')
    return p


def _records_url(key, filters, part=''):
    q = filters.as_query()
    if part:
        q['part'] = part
    return f"{reverse('executive:records', args=[key])}?{urlencode(q)}"


def _filter_choices(visible):
    from core.models import Organization
    from locations.models import Location
    from psa.models import Contract
    ids, unlimited = set(), False
    for _p, scope in visible:
        if scope.org_ids is None:
            unlimited = True
            break
        ids |= scope.org_ids
    orgs = Organization.objects.filter(is_active=True)
    if not unlimited:
        orgs = orgs.filter(pk__in=ids)
    customers = list(orgs.order_by('name').values('pk', 'name')[:2000])
    locs = Location.objects.all()
    if not unlimited:
        locs = locs.filter(organization_id__in=ids)
    locations = list(locs.select_related('organization').order_by('organization__name', 'name')
                     .values('pk', 'name', 'organization__name')[:2000])
    return customers, Contract.CONTRACT_TYPES, locations


@login_required
@require_GET
@require_msp_wide_perm('reports_view_dashboards', legacy='staff')
def overview(request):
    _staff_only(request)
    filters = metrics.Filters.from_query(request.GET)
    visible = _visible(request.user)
    customers, service_lines, locations = _filter_choices(visible)
    query = urlencode(filters.as_query())
    cards = []
    for p, _scope in visible:
        meta = p.meta()
        meta['url'] = f"{reverse('executive:metric', args=[p.key])}?{query}"
        meta['records_url'] = _records_url(p.key, filters)
        meta['unsupported'] = [metrics.FILTER_LABELS[f] for f in filters.active()
                               if f not in p.supported_filters]
        cards.append(meta)
    sections = []
    for card in cards:
        if not sections or sections[-1]['name'] != card['section']:
            sections.append({'name': card['section'], 'cards': []})
        sections[-1]['cards'].append(card)
    return render(request, 'executive/overview.html', {
        'filters': filters,
        'sections': sections,
        'cards': cards,
        'hidden_count': len(providers.PROVIDERS) - len(cards),
        'customers': customers,
        'service_lines': service_lines,
        'locations': locations,
        'filter_labels': metrics.FILTER_LABELS,
        'card_filters': {c['key']: c['supported_filters'] for c in cards},
    })


@login_required
@require_GET
@require_msp_wide_perm('reports_view_dashboards', legacy='staff')
def metric(request, key):
    _staff_only(request)
    p = _provider_or_404(request.user, key)
    filters = metrics.Filters.from_query(request.GET)
    result = metrics.compute(p, request.user, filters,
                             drilldown_url=_records_url(key, filters.for_provider(p.supported_filters)))
    data = result.to_dict()
    data['permission_note'] = p.permission_note
    data['generated_at'] = timezone.now().isoformat()
    for item in data.get('breakdown') or []:
        if item.get('part'):
            item['url'] = _records_url(key, filters.for_provider(p.supported_filters), item['part'])
    return JsonResponse(data)


@login_required
@require_GET
@require_msp_wide_perm('reports_view_dashboards', legacy='staff')
def records(request, key):
    _staff_only(request)
    p = _provider_or_404(request.user, key)
    filters = metrics.Filters.from_query(request.GET)
    part = (request.GET.get('part') or '').strip()[:40]
    result, columns, rows, capped = metrics.drilldown(p, request.user, filters, part=part)
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'key': key, 'state': result.state, 'reason': result.reason, 'part': part,
            'value': metrics._plain(result.value), 'unit': result.unit,
            'is_complete': result.is_complete, 'unknown_reason': result.unknown_reason,
            'columns': [{'key': c.key, 'label': c.label, 'kind': c.kind} for c in columns],
            'rows': rows, 'count': len(rows), 'capped': capped,
        }, status=403 if result.state == metrics.STATE_FORBIDDEN else 200)
    if result.state == metrics.STATE_FORBIDDEN:
        raise PermissionDenied(result.reason)
    def cell(value, kind):
        if kind == 'date' and isinstance(value, str):
            value = value[:16].replace('T', ' ')
        return {'value': value, 'kind': kind}
    table = [[cell(r.get(c.key), c.kind) for c in columns] + [{'url': r.get('url', '')}]
             for r in rows]
    return render(request, 'executive/records.html', {
        'provider': p, 'result': result, 'columns': columns, 'table': table, 'capped': capped,
        'part': part, 'filters': filters, 'limit': metrics.DRILLDOWN_LIMIT,
        'back_url': f"{reverse('executive:overview')}?{urlencode(filters.as_query())}",
        'ignored': [metrics.FILTER_LABELS[f] for f in result.ignored_filters],
    })
