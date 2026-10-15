"""
Portal "Request a service" — guided service requests.

Customers browse the catalog items available to their organization, fill
in a form generated from the item's `form_schema`, see the expected
turnaround and whether an approval is needed, get pointed at relevant KB
articles first, and submit. Submission creates a client-visible ticket
routed per the item (psa/service_requests.py: submit_request).
"""
from __future__ import annotations

import re
from collections import OrderedDict

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from psa.service_requests import (
    FIELD_PREFIX, portal_catalog_for, service_request_record, submit_request,
    validate_submission,
)

from .views import _portal_feature_enabled, portal_kb_queryset, portal_psa_required

_STOPWORDS = {
    'a', 'an', 'and', 'the', 'for', 'to', 'of', 'in', 'on', 'or', 'my', 'new',
    'request', 'please', 'with', 'from', 'this', 'that', 'need', 'help', 'our',
    'your', 'is', 'are', 'be', 'it', 'we', 'i', 'you', 'can', 'not',
}


def _terms(*texts, limit=8):
    words = []
    for t in texts:
        for w in re.findall(r'[A-Za-z0-9][A-Za-z0-9\-]{2,}', t or ''):
            lw = w.lower()
            if lw not in _STOPWORDS and lw not in words:
                words.append(lw)
    return words[:limit]


def suggest_kb_articles(organization, *texts, limit=5):
    """KB articles this customer may read whose title (or body) mentions the
    request's words. Titles rank above body matches."""
    from django.db.models import Q
    terms = _terms(*texts)
    if not terms:
        return []
    qs = portal_kb_queryset(organization)
    title_q = Q()
    body_q = Q()
    for t in terms:
        title_q |= Q(title__icontains=t)
        body_q |= Q(body__icontains=t)
    picked = list(qs.filter(title_q).order_by('-portal_view_count', '-updated_at')[:limit])
    if len(picked) < limit:
        more = (qs.filter(body_q).exclude(pk__in=[d.pk for d in picked])
                .order_by('-portal_view_count', '-updated_at')[:limit - len(picked)])
        picked.extend(more)
    return picked


def _available_item(request, slug):
    item = portal_catalog_for(request.portal_membership.organization) \
        .select_related('default_queue', 'default_type', 'default_priority') \
        .filter(slug=slug).first()
    if item is None:
        raise Http404('Service not available')
    return item


@portal_psa_required
def request_catalog(request):
    """Catalog items available to the active customer, grouped by category."""
    m = request.portal_membership
    groups = OrderedDict()
    items = sorted(portal_catalog_for(m.organization),
                   key=lambda i: ((i.category or '~').lower(), i.sort_order, i.name))
    for item in items:
        groups.setdefault(item.category or 'Other', []).append(item)
    return render(request, 'portal/request_catalog.html', {
        'organization': m.organization,
        'groups': list(groups.items()),
    })


@portal_psa_required
@require_http_methods(['GET', 'POST'])
def request_form(request, slug):
    m = request.portal_membership
    item = _available_item(request, slug)
    schema = item.get_form_schema()
    errors = []
    submitted = {}

    if request.method == 'POST':
        answers, errors = validate_submission(schema, request.POST)
        if not errors:
            try:
                ticket = submit_request(item=item, organization=m.organization,
                                        user=request.user, answers=answers)
            except ValueError:
                messages.error(request, 'Requests are not configured yet. Please contact support.')
                return redirect('portal:request_catalog')
            AuditLog.log(
                user=request.user, action='create',
                organization=m.organization,
                object_type='psa.Ticket', object_id=ticket.pk,
                object_repr=ticket.ticket_number,
                description=f'Portal service request {ticket.ticket_number}: {item.name}',
                path=request.path,
            )
            if item.needs_customer_approval:
                messages.success(request, f'Request {ticket.ticket_number} submitted. '
                                          f'It will start once it has been approved.')
            else:
                messages.success(request, f'Request {ticket.ticket_number} submitted.')
            return redirect('portal:ticket_detail', ticket_number=ticket.ticket_number)
        # Re-render with what they typed (only known fields).
        for f in schema:
            name = FIELD_PREFIX + f['key']
            if f['type'] == 'multiselect':
                submitted[f['key']] = request.POST.getlist(name)
            else:
                submitted[f['key']] = request.POST.get(name, '')

    fields = []
    for f in schema:
        fd = dict(f)
        fd['input_name'] = FIELD_PREFIX + f['key']
        fd['current'] = submitted.get(f['key'], [] if f['type'] == 'multiselect' else '')
        fields.append(fd)

    return render(request, 'portal/request_form.html', {
        'organization': m.organization,
        'item': item,
        'fields': fields,
        'schema': schema,
        'errors': errors,
        'kb_suggestions': suggest_kb_articles(
            m.organization, item.name, item.category, item.description),
        'approvals_enabled': _portal_feature_enabled('psa_portal_customer_approvals_enabled'),
    }, status=400 if errors else 200)


@portal_psa_required
def request_kb_suggest(request, slug):
    """JSON: KB articles matching what the customer has typed so far."""
    m = request.portal_membership
    item = _available_item(request, slug)
    q = (request.GET.get('q') or '')[:500]
    docs = suggest_kb_articles(m.organization, q) if q.strip() else \
        suggest_kb_articles(m.organization, item.name, item.category, item.description)
    from django.urls import reverse
    return JsonResponse({'articles': [
        {'title': d.title, 'url': reverse('portal:kb_detail', args=[d.slug])}
        for d in docs
    ]})


def service_request_context(ticket):
    """Display data for a ticket created by a guided request, or None."""
    record = service_request_record(ticket)
    if not record:
        return None
    rows = [r for r in (record.get('answers') or []) if isinstance(r, dict)]
    due = None
    hours = record.get('expected_turnaround_hours')
    if hours and record.get('submitted_at'):
        from datetime import datetime, timedelta
        try:
            due = datetime.fromisoformat(record['submitted_at']) + timedelta(hours=int(hours))
        except (TypeError, ValueError):
            due = None
    return {
        'name': record.get('catalog_item_name') or '',
        'answers': rows,
        'expected_turnaround': record.get('expected_turnaround') or '',
        'expected_by': due,
        'approval_required': bool(record.get('approval_required')),
    }
