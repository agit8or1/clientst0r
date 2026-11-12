"""
Portal "New ticket" — request types and dynamic request forms.

Customers pick what they need on a "What do you need help with?" screen
(the request types available to their organization and portal role, plus
an always-present general support option), fill in a form generated from
the request type's published form version, see the expected turnaround and
whether an approval is needed, get pointed at relevant KB articles first,
and submit. Submission creates one client-visible ticket routed per the
request type (psa/service_requests.py: submit_request).

Nothing the browser sends decides the organization, the request type's
form, lookup scope or routing: those come from the server-side portal
membership and the published form version.
"""
from __future__ import annotations

import re
import uuid
from collections import OrderedDict

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from audit.models import AuditLog
from psa import request_lookups
from psa.service_requests import (
    CHOICE_TYPES, FIELD_PREFIX, TEXT_SUFFIX, TZ_SUFFIX, DuplicateSubmission, FormContext,
    initial_values, option_pairs, portal_catalog_for, service_request_record, submit_request,
    valid_token, validate_submission,
)

from .views import (
    PORTAL_TICKETS_CREATE, _portal_feature_enabled, portal_kb_queryset, portal_psa_required,
    require_portal_perm,
)

_STOPWORDS = {
    'a', 'an', 'and', 'the', 'for', 'to', 'of', 'in', 'on', 'or', 'my', 'new',
    'request', 'please', 'with', 'from', 'this', 'that', 'need', 'help', 'our',
    'your', 'is', 'are', 'be', 'it', 'we', 'i', 'you', 'can', 'not',
}

COMMON_TIMEZONES = [
    'UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Phoenix',
    'America/Los_Angeles', 'America/Anchorage', 'Pacific/Honolulu', 'America/Toronto',
    'America/Vancouver', 'America/Halifax', 'America/Mexico_City', 'America/Sao_Paulo',
    'Europe/London', 'Europe/Dublin', 'Europe/Lisbon', 'Europe/Paris', 'Europe/Berlin',
    'Europe/Madrid', 'Europe/Rome', 'Europe/Amsterdam', 'Europe/Stockholm', 'Europe/Warsaw',
    'Europe/Athens', 'Europe/Istanbul', 'Africa/Johannesburg', 'Asia/Dubai', 'Asia/Kolkata',
    'Asia/Singapore', 'Asia/Hong_Kong', 'Asia/Tokyo', 'Australia/Perth', 'Australia/Sydney',
    'Pacific/Auckland',
]


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
    from docs.kb_visibility import client_body_matches
    qs = portal_kb_queryset(organization)
    title_q = Q()
    for t in terms:
        title_q |= Q(title__icontains=t)
    picked = list(qs.filter(title_q).order_by('-portal_view_count', '-updated_at')[:limit])
    if len(picked) < limit:
        # Body matches count only on what the customer can see (no internal-only blocks).
        more = (qs.filter(pk__in=client_body_matches(qs, terms)).exclude(pk__in=[d.pk for d in picked])
                .order_by('-portal_view_count', '-updated_at')[:limit - len(picked)])
        picked.extend(more)
    return picked


def _available_item(request, slug):
    m = request.portal_membership
    item = portal_catalog_for(m.organization, membership=m) \
        .select_related('default_queue', 'default_type', 'default_priority') \
        .filter(slug=slug).first()
    if item is None:
        raise Http404('Service not available')
    return item


def form_context(request):
    m = request.portal_membership
    return FormContext(organization=m.organization, user=request.user, membership=m)


# ---------------------------------------------------------------------------
# "What do you need help with?"
# ---------------------------------------------------------------------------

def picker_context(membership):
    """Request types grouped by category, plus the general-support entry."""
    items = sorted(portal_catalog_for(membership.organization, membership=membership),
                   key=lambda i: ((i.category or '~').lower(), i.sort_order, i.name.lower()))
    general = next((i for i in items if i.starter_key == 'general_support'), None)
    groups = OrderedDict()
    for item in items:
        if item is general:
            continue
        groups.setdefault(item.category or 'Other', []).append(item)
    return {
        'groups': list(groups.items()),
        'general_item': general,
        'has_request_types': bool(items),
    }


@portal_psa_required
def request_catalog(request):
    """The request-type picker (also what "New ticket" shows)."""
    m = request.portal_membership
    return render(request, 'portal/request_catalog.html', {
        'organization': m.organization, **picker_context(m),
    })


# ---------------------------------------------------------------------------
# The form
# ---------------------------------------------------------------------------

def _posted_values(schema, post):
    """What the customer typed, for re-display only (known fields only)."""
    values = {}
    for f in schema:
        name = FIELD_PREFIX + f['key']
        if f['type'] == 'multiselect':
            values[f['key']] = post.getlist(name)
        elif f['type'] in ('contact', 'asset'):
            values[f['key']] = {'id': post.get(name, ''), 'text': post.get(name + TEXT_SUFFIX, '')}
        elif f['type'] == 'datetime':
            values[f['key']] = {'value': post.get(name, ''), 'tz': post.get(name + TZ_SUFFIX, '')}
        elif f['type'] not in ('file', 'heading', 'info'):
            values[f['key']] = post.get(name, '')
    return values


def build_fields(schema, values, ctx, field_errors=None, *, preview=False):
    """Render data for each field of `schema`."""
    from django.conf import settings as django_settings
    field_errors = field_errors or {}
    out = []
    for f in schema:
        fd = dict(f)
        fd['input_name'] = FIELD_PREFIX + f['key']
        fd['dom_id'] = 'id_' + fd['input_name']
        fd['error'] = field_errors.get(f['key'], '')
        cur = values.get(f['key'])
        if f['type'] in CHOICE_TYPES:
            fd['pairs'] = option_pairs(f)
        if f['type'] == 'multiselect':
            fd['current'] = [str(v) for v in (cur or [])] if isinstance(cur, list) else []
        elif f['type'] == 'checkbox':
            fd['current'] = cur in (True, 'on', 'true', '1', 'yes')
        elif f['type'] in ('contact', 'asset'):
            cur = cur if isinstance(cur, dict) else {}
            fd['current_id'] = str(cur.get('id') or '')
            fd['current_text'] = cur.get('text') or ''
            fd['current_label'] = ''
            if fd['current_id'].isdigit() and ctx is not None and not preview:
                found = request_lookups.resolve(f, int(fd['current_id']), ctx)
                fd['current_label'] = found['label'] if found else ''
                if not found:
                    fd['current_id'] = ''
            fd['scope_note'] = request_lookups.scope_note(f, ctx) if ctx is not None else ''
            fd['searchable'] = (not preview and request_lookups.can_search(f, ctx))
            fd['own_options'] = ([] if preview or ctx is None or
                                 request_lookups.can_search(f, ctx)
                                 else request_lookups.search(f, '', ctx))
        elif f['type'] == 'location':
            fd['current'] = str((cur.get('id') if isinstance(cur, dict) else cur) or '')
            fd['location_options'] = request_lookups.location_options(ctx) if ctx is not None else []
        elif f['type'] == 'datetime':
            cur = cur if isinstance(cur, dict) else {}
            fd['current'] = cur.get('value') or ''
            fd['current_tz'] = cur.get('tz') or getattr(django_settings, 'TIME_ZONE', 'UTC')
            zones = list(COMMON_TIMEZONES)
            if fd['current_tz'] not in zones:
                zones.insert(0, fd['current_tz'])
            fd['timezones'] = zones
        else:
            fd['current'] = '' if cur is None else cur
        out.append(fd)
    return out


def _render_form(request, item, version, schema, values, *, errors=(), field_errors=None,
                 token=None, notice='', status=200):
    m = request.portal_membership
    ctx = form_context(request)
    return render(request, 'portal/request_form.html', {
        'organization': m.organization,
        'item': item,
        'fields': build_fields(schema, values, ctx, field_errors),
        'schema': schema,
        'errors': list(errors),
        'notice': notice,
        'form_version': getattr(version, 'number', ''),
        'submission_token': token or uuid.uuid4().hex,
        'has_files': any(f['type'] == 'file' for f in schema),
        'kb_suggestions': suggest_kb_articles(
            m.organization, item.name, item.category, item.description),
        'approvals_enabled': _portal_feature_enabled('psa_portal_customer_approvals_enabled'),
        'preview': False,
    }, status=status)


def _success_message(item, ticket):
    msg = f'Request {ticket.ticket_number} submitted.'
    if item.needs_customer_approval:
        msg += ' It will start once it has been approved.'
    if item.confirmation_message:
        msg += ' ' + item.confirmation_message
    return msg


@portal_psa_required
@require_http_methods(['GET', 'POST'])
@ratelimit(key='user', rate='30/h', method='POST', block=False)
def request_form(request, slug):
    from psa.models import ServiceRequestSubmission
    from psa.request_forms import ensure_version

    m = request.portal_membership
    # A request files a ticket: same role permission as the plain form.
    require_portal_perm(request, PORTAL_TICKETS_CREATE)
    item = _available_item(request, slug)
    version = ensure_version(item)
    schema = list(version.schema) if version is not None else item.get_form_schema()

    if request.method != 'POST':
        return _render_form(request, item, version, schema, initial_values(schema))

    token = (request.POST.get('_submission_token') or '').strip()
    values = _posted_values(schema, request.POST)
    if getattr(request, 'limited', False):
        return _render_form(request, item, version, schema, values, token=token, status=429,
                            errors=['You have sent a lot of requests in the last hour. '
                                    'Please wait a little and try again.'])

    # A repeated POST (double click, browser retry) gets the first ticket.
    if valid_token(token):
        earlier = (ServiceRequestSubmission.objects.select_related('ticket')
                   .filter(idempotency_key=token).first())
        if earlier is not None:
            if (earlier.submitted_by_id == request.user.pk and earlier.ticket_id
                    and earlier.organization_id == m.organization_id):
                messages.info(request, f'Request {earlier.ticket.ticket_number} was already '
                                       f'submitted; it was not sent twice.')
                return redirect('portal:ticket_detail', ticket_number=earlier.ticket.ticket_number)
            token = ''  # someone else's token: never reuse it

    posted_version = (request.POST.get('_form_version') or '').strip()
    field_errors = {}
    answers, errors = validate_submission(schema, request.POST, request.FILES,
                                          form_context(request), field_errors)
    if version is not None and posted_version and posted_version != str(version.number):
        # The form was republished while they were filling it in: keep their
        # answers, show the current form, and ask them to check and resend.
        return _render_form(
            request, item, version, schema, values, errors=errors, field_errors=field_errors,
            token=token, status=409,
            notice=('This form was updated while you were filling it in. Your answers are '
                    'kept below; please check them (and re-attach any files) and submit again.'))
    if errors:
        if any(f['type'] == 'file' for f in schema):
            errors.append('For your security, attached files are not kept when the form '
                          'has a problem — please attach them again.')
        return _render_form(request, item, version, schema, values, errors=errors,
                            field_errors=field_errors, token=token, status=400)
    try:
        ticket = submit_request(item=item, organization=m.organization, user=request.user,
                                answers=answers, token=token, version=version)
    except DuplicateSubmission as dup:
        t = dup.submission.ticket
        if t is not None and dup.submission.submitted_by_id == request.user.pk:
            messages.info(request, f'Request {t.ticket_number} was already submitted.')
            return redirect('portal:ticket_detail', ticket_number=t.ticket_number)
        raise Http404()
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
        extra_data={'request_type_id': item.pk,
                    'form_version': getattr(version, 'number', None)},
    )
    messages.success(request, _success_message(item, ticket))
    return redirect('portal:ticket_detail', ticket_number=ticket.ticket_number)


@portal_psa_required
@ratelimit(key='user', rate='120/m', method='GET', block=False)
def request_lookup(request, slug, key):
    """JSON type-ahead for one lookup field of the published form. Scoped
    by psa/request_lookups.py to what this person may see."""
    from psa.request_forms import ensure_version
    if getattr(request, 'limited', False):
        return JsonResponse({'results': [], 'error': 'Too many lookups'}, status=429)
    item = _available_item(request, slug)
    version = ensure_version(item)
    schema = list(version.schema) if version is not None else item.get_form_schema()
    field = next((f for f in schema if f['key'] == key and f['type'] in ('contact', 'asset', 'location')),
                 None)
    if field is None:
        raise Http404()
    results = request_lookups.search(field, request.GET.get('q') or '', form_context(request))
    return JsonResponse({'results': results})


@portal_psa_required
def request_kb_suggest(request, slug):
    """JSON: KB articles matching what the customer has typed so far."""
    m = request.portal_membership
    item = _available_item(request, slug)
    q = (request.GET.get('q') or '')[:500]
    docs = suggest_kb_articles(m.organization, q) if q.strip() else \
        suggest_kb_articles(m.organization, item.name, item.category, item.description)
    return JsonResponse({'articles': [
        {'title': d.title, 'url': reverse('portal:kb_detail', args=[d.slug])}
        for d in docs
    ]})


# ---------------------------------------------------------------------------
# Request details on the ticket
# ---------------------------------------------------------------------------

def can_view_request_details(ticket, record, membership, user):
    """Customer side: the person who asked, the customer's portal admins and
    the people who may approve it see the answers. Other portal users at the
    customer see the ticket but not the (possibly personal) details."""
    if membership is None or membership.organization_id != ticket.organization_id:
        return False
    if user.pk in (record.get('submitted_by_id'), ticket.created_by_id):
        return True
    if membership.is_org_admin and membership.is_active:
        return True
    approval_id = record.get('approval_id')
    if approval_id:
        from psa.models import PSAApproval
        from psa.service_requests import approvers_for_approval
        a = PSAApproval.objects.filter(pk=approval_id, related_ticket=ticket).first()
        if a is not None and any(u.pk == user.pk for u in approvers_for_approval(a)['users']):
            return True
    return False


def service_request_context(ticket, membership=None, user=None):
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
    can_view = True if user is None else can_view_request_details(ticket, record, membership, user)
    return {
        'name': record.get('catalog_item_name') or '',
        'answers': rows if can_view else [],
        'answers_hidden': not can_view,
        'expected_turnaround': record.get('expected_turnaround') or '',
        'expected_by': due,
        'approval_required': bool(record.get('approval_required')),
        'approval_status': record.get('approval_status') or '',
    }
