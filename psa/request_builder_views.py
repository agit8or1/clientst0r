"""
Staff pages for portal request types: list, form builder, preview,
publish / disable / archive, duplicates and customer copies, starter
templates, routing preview, request-answer edits and a simple report.

Who: MSP admins (superusers and MSP staff users — the same people who edit
the service catalog). A customer's own copy also needs ticket access at
that customer. Publishing an item under change governance needs
`catalog_approve_change`; without it, Publish files a change proposal.
"""
from __future__ import annotations

import json
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog

from . import request_forms, request_starters
from .feature_flags import require_psa_enabled
from .models import (
    Queue, ServiceCatalogItem, ServiceRequestSubmission, Ticket, TicketPriority, TicketType,
)
from .service_requests import (
    CONDITION_OPS, FIELD_TYPES, OP_LABELS, TYPE_LABELS, SchemaError, normalize_schema,
)

ICON_RE = re.compile(r'^[a-z0-9 -]{0,80}$')


def _ip(request):
    try:
        from core.client_ip import get_client_ip
        return get_client_ip(request)
    except Exception:  # noqa: BLE001
        return request.META.get('REMOTE_ADDR')


def _require_admin(request):
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        raise Http404()


def _item_for(request, pk):
    _require_admin(request)
    item = get_object_or_404(ServiceCatalogItem.objects.select_related('organization', 'based_on'),
                             pk=pk)
    if not request_forms.staff_may_manage(request.user, item):
        raise Http404()
    return item


def _audit(request, item, action, description, extra=None):
    AuditLog.log(
        user=request.user, action=action, organization=item.organization,
        object_type='psa.ServiceCatalogItem', object_id=item.pk, object_repr=item.name,
        description=description, ip_address=_ip(request), path=request.path,
        extra_data=extra or {},
    )


def _can_publish_directly(user, item):
    if not item.requires_approval:
        return True
    from accounts.permission_utils import user_has_perm
    return user_has_perm(user, 'catalog_approve_change')


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
def request_type_list(request):
    _require_admin(request)
    from accounts.permission_utils import orgs_with_perm
    show = request.GET.get('show') or 'current'
    qs = (ServiceCatalogItem.objects.select_related('organization', 'based_on', 'published_version')
          .annotate(n_submissions=Count('submissions')))
    if show == 'archived':
        qs = qs.filter(lifecycle=ServiceCatalogItem.LIFECYCLE_ARCHIVED)
    else:
        qs = qs.exclude(lifecycle=ServiceCatalogItem.LIFECYCLE_ARCHIVED)
    allowed = orgs_with_perm(request.user, 'tickets_view')
    if allowed is not None:
        qs = qs.filter(Q(organization__isnull=True) | Q(organization_id__in=allowed))
    items = list(qs.order_by('organization__name', 'category', 'sort_order', 'name'))
    from core.models import Organization
    orgs = Organization.objects.filter(is_active=True).order_by('name')
    if allowed is not None:
        orgs = orgs.filter(pk__in=allowed)
    return render(request, 'psa/request_types/list.html', {
        'items': items, 'show': show, 'organizations': orgs,
        'starters': request_starters.STARTERS,
    })


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def request_type_move(request, pk):
    """Move a request type up or down within its category (display order)."""
    item = _item_for(request, pk)
    direction = request.POST.get('direction')
    siblings = list(ServiceCatalogItem.objects
                    .filter(organization=item.organization, category=item.category)
                    .exclude(lifecycle=ServiceCatalogItem.LIFECYCLE_ARCHIVED)
                    .order_by('sort_order', 'name', 'pk'))
    idx = next((i for i, s in enumerate(siblings) if s.pk == item.pk), None)
    j = idx + (-1 if direction == 'up' else 1) if idx is not None else None
    if j is not None and 0 <= j < len(siblings):
        siblings[idx], siblings[j] = siblings[j], siblings[idx]
        with transaction.atomic():
            for n, s in enumerate(siblings):
                if s.sort_order != (n + 1) * 10:
                    ServiceCatalogItem.objects.filter(pk=s.pk).update(sort_order=(n + 1) * 10)
        _audit(request, item, 'update', f'Moved request type "{item.name}" {direction}')
    return redirect(request.POST.get('next') or reverse('psa:request_type_list'))


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def request_type_action(request, pk):
    """enable / disable / archive / restore / duplicate / copy for customer."""
    from core.models import Organization
    item = _item_for(request, pk)
    action = request.POST.get('action')
    if action in ('enable', 'disable'):
        item.is_active = action == 'enable'
        item.save(update_fields=['is_active', 'updated_at'])
        _audit(request, item, 'update', f'{"Enabled" if item.is_active else "Disabled"} request type "{item.name}"')
        messages.success(request, f'"{item.name}" {"enabled" if item.is_active else "disabled"}.')
    elif action == 'archive':
        request_forms.archive(item, request.user)
        _audit(request, item, 'update', f'Archived request type "{item.name}"; existing tickets keep their details')
        messages.success(request, f'Archived "{item.name}". Tickets raised from it keep their request details.')
    elif action == 'restore':
        request_forms.restore(item, request.user)
        _audit(request, item, 'update', f'Restored request type "{item.name}"')
        messages.success(request, f'Restored "{item.name}".')
    elif action in ('duplicate', 'copy_for_customer'):
        org = None
        if action == 'copy_for_customer':
            try:
                org = Organization.objects.get(pk=int(request.POST.get('organization_id') or 0),
                                               is_active=True)
            except (Organization.DoesNotExist, ValueError):
                messages.error(request, 'Pick a customer.')
                return redirect('psa:request_type_builder', pk=item.pk)
            if not request_forms.staff_may_manage(request.user, organization=org):
                raise Http404()
        try:
            copy = request_forms.duplicate(item, request.user, organization=org)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('psa:request_type_builder', pk=item.pk)
        _audit(request, copy, 'create',
               f'Copied request type "{item.name}" to "{copy.name}"'
               + (f' for {org.name}' if org else ''), {'source_id': item.pk})
        messages.success(request, f'Created draft "{copy.name}"'
                         + (f' for {org.name}. Publish it to replace the shared version for them.' if org else '.'))
        return redirect('psa:request_type_builder', pk=copy.pk)
    else:
        messages.error(request, 'Unknown action.')
    return redirect(request.POST.get('next') or reverse('psa:request_type_builder', args=[item.pk]))


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def request_type_starters(request):
    _require_admin(request)
    if request.method == 'POST':
        key = request.POST.get('starter')
        if key not in request_starters.BY_KEY:
            messages.error(request, 'Unknown starter template.')
            return redirect('psa:request_type_starters')
        item = request_starters.install(key, request.user)
        _audit(request, item, 'create', f'Added starter request type "{item.name}" as a draft',
               {'starter': key})
        messages.success(request, f'Added "{item.name}" as a draft. Review it, then publish.')
        return redirect('psa:request_type_builder', pk=item.pk)
    installed = set(ServiceCatalogItem.objects.exclude(starter_key='')
                    .values_list('starter_key', flat=True))
    return render(request, 'psa/request_types/starters.html', {
        'starters': [dict(s, installed=s['key'] in installed,
                          field_count=len([f for f in s['schema'] if f['type'] not in ('heading', 'info')]))
                     for s in request_starters.STARTERS],
    })


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def request_type_new(request):
    """A blank request type (draft) straight into the builder."""
    _require_admin(request)
    name = (request.POST.get('name') or '').strip()[:120] or 'New request type'
    base, n = name, 1
    while request_forms.name_taken(name, None):
        n += 1
        name = f'{base} ({n})'
    item = ServiceCatalogItem.objects.create(
        name=name, slug=request_forms.unique_slug(name), lifecycle=ServiceCatalogItem.LIFECYCLE_DRAFT,
        portal_visible=True, is_active=True, draft_schema=[],
        draft_updated_at=timezone.now(), draft_updated_by=request.user,
    )
    _audit(request, item, 'create', f'Created request type "{item.name}" (draft)')
    return redirect('psa:request_type_builder', pk=item.pk)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _int_or_none(raw):
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _save_settings(request, item):
    """Request-type settings (not the form). Returns an error or None."""
    from django.contrib.auth.models import Group, User
    from psa.visibility import msp_staff_q
    p = request.POST
    name = (p.get('name') or '').strip()[:120]
    if not name:
        return 'Give the request type a name.'
    if request_forms.name_taken(name, item.organization, exclude_pk=item.pk):
        return f'Another request type{" for this customer" if item.organization else ""} is already called "{name}".'
    icon = (p.get('icon') or '').strip()[:80]
    if not ICON_RE.match(icon):
        return 'Icon must be a Font Awesome class such as "fas fa-user-plus".'
    try:
        sort_order = max(0, int(p.get('sort_order') or 0))
    except ValueError:
        return 'Display order must be a whole number.'
    hours_raw = (p.get('expected_turnaround_hours') or '').strip()
    hours = _int_or_none(hours_raw) if hours_raw else None
    if hours_raw and hours is None:
        return 'Expected turnaround hours must be a whole number.'
    audience = p.get('portal_audience') or ServiceCatalogItem.AUDIENCE_EVERYONE
    if audience not in dict(ServiceCatalogItem.AUDIENCE_CHOICES):
        return 'Pick who sees this request type.'
    policy = p.get('approval_policy') or ServiceCatalogItem.APPROVAL_NONE
    if policy not in dict(ServiceCatalogItem.APPROVAL_POLICY_CHOICES):
        return 'Pick a valid approval policy.'

    def pick(qs, name):
        pk = _int_or_none(p.get(name))
        return qs.filter(pk=pk).first() if pk else None

    assignee_id = _int_or_none(p.get('default_assignee'))
    assignee = (User.objects.filter(msp_staff_q(), is_active=True, pk=assignee_id).distinct().first()
                if assignee_id else None)
    if assignee_id and assignee is None:
        return 'The default technician must be an active MSP technician.'
    if assignee is not None and item.organization is not None:
        from psa.routing.engine import _authorization_problem, customer_settings
        cust = customer_settings(item.organization)
        ids = set(cust.authorized_technicians.values_list('pk', flat=True)) if cust else set()
        why = _authorization_problem(assignee, item.organization, cust, ids)
        if why:
            return f'{assignee.get_username()} cannot be the default technician: {why}.'
    item.name = name
    item.description = (p.get('description') or '').strip()[:2000]
    item.category = (p.get('category') or '').strip()[:80]
    item.icon = icon
    item.sort_order = sort_order
    item.portal_visible = p.get('portal_visible') == 'on'
    item.portal_audience = audience
    item.confirmation_message = (p.get('confirmation_message') or '').strip()[:2000]
    item.default_subject = (p.get('default_subject') or '').strip()[:300]
    item.default_queue = pick(Queue.objects.filter(is_active=True), 'default_queue')
    item.default_priority = pick(TicketPriority.objects.all(), 'default_priority')
    item.default_type = pick(TicketType.objects.filter(is_active=True), 'default_type')
    item.default_team = pick(Group.objects.all(), 'default_team')
    item.default_assignee = assignee
    item.approval_policy = policy
    item.approval_allow_self = p.get('approval_allow_self') == 'on'
    item.expected_turnaround_text = (p.get('expected_turnaround_text') or '').strip()[:120]
    item.expected_turnaround_hours = hours
    item.save()
    if item.organization_id is None:
        from core.models import Organization
        valid = set(Organization.objects.filter(is_active=True).values_list('pk', flat=True))
        inc = sorted({int(v) for v in p.getlist('include_organizations') if v.isdigit()} & valid)
        exc = sorted({int(v) for v in p.getlist('exclude_organizations') if v.isdigit()} & valid)
        item.include_organizations.set(inc)
        item.exclude_organizations.set(exc)
    return None


def _builder_context(item, user, schema_override=None, schema_error=''):
    from django.contrib.auth.models import Group, User
    from core.models import Organization
    from psa.routing.models import RoutingRule
    from psa.visibility import msp_staff_q
    schema = schema_override if schema_override is not None else request_forms.draft_or_live_schema(item)
    rules = [r for r in RoutingRule.objects.filter(current_version__isnull=False)
             .select_related('current_version', 'organization')
             if item.slug in ((r.current_version.conditions or {}).get('services') or [])]
    return {
        'item': item,
        'schema_json': json.dumps(schema, indent=1),
        'schema_error': schema_error,
        'type_choices': [(t, TYPE_LABELS[t]) for t in FIELD_TYPES],
        'op_choices': [(o, OP_LABELS[o]) for o in CONDITION_OPS],
        'has_draft': request_forms.has_unpublished_changes(item),
        'versions': item.form_versions.select_related('published_by')[:20],
        'live_version': request_forms.latest_version(item),
        'can_publish_directly': _can_publish_directly(user, item),
        'queues': Queue.objects.filter(is_active=True).order_by('name'),
        'priorities': TicketPriority.objects.order_by('sort_order', 'code'),
        'types': TicketType.objects.filter(is_active=True).order_by('name'),
        'teams': Group.objects.order_by('name'),
        'technicians': User.objects.filter(msp_staff_q(), is_active=True).distinct().order_by('username'),
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'include_ids': set(item.include_organizations.values_list('pk', flat=True)),
        'exclude_ids': set(item.exclude_organizations.values_list('pk', flat=True)),
        'audience_choices': ServiceCatalogItem.AUDIENCE_CHOICES,
        'approval_choices': ServiceCatalogItem.APPROVAL_POLICY_CHOICES,
        'routing_rules': rules,
        'copies': item.customer_copies.select_related('organization').all() if item.pk else [],
        'submission_count': item.submissions.count(),
        'locked_keys': sorted({f.get('key') for v in item.form_versions.all() for f in (v.schema or [])}
                              if item.pk else []),
    }


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def request_type_builder(request, pk):
    item = _item_for(request, pk)
    if request.method == 'POST':
        action = request.POST.get('action') or 'save_draft'
        if action == 'settings':
            if not _can_publish_directly(request.user, item):
                messages.error(request, 'This request type is under change governance: propose '
                                        'settings changes from the service catalog instead.')
                return redirect('psa:request_type_builder', pk=item.pk)
            err = _save_settings(request, item)
            if err:
                messages.error(request, err)
            else:
                _audit(request, item, 'update', f'Updated settings of request type "{item.name}"')
                messages.success(request, 'Settings saved.')
            return redirect('psa:request_type_builder', pk=item.pk)
        if action == 'discard':
            item.draft_schema = None
            item.save(update_fields=['draft_schema', 'updated_at'])
            messages.info(request, 'Draft discarded; the published form is unchanged.')
            return redirect('psa:request_type_builder', pk=item.pk)
        try:
            raw = json.loads(request.POST.get('schema_json') or '[]')
            schema = request_forms.save_draft(item, raw, request.user)
        except (ValueError, SchemaError) as e:
            msg = str(e) if isinstance(e, SchemaError) else f'The form definition is not valid JSON: {e}'
            ctx = _builder_context(item, request.user, schema_error=msg)
            try:
                ctx['schema_json'] = json.dumps(json.loads(request.POST.get('schema_json') or '[]'), indent=1)
            except ValueError:
                ctx['schema_json'] = request.POST.get('schema_json') or '[]'
            messages.error(request, msg)
            return render(request, 'psa/request_types/builder.html', ctx, status=400)
        if action == 'preview':
            return redirect(reverse('psa:request_type_preview', args=[item.pk])
                            + f'?draft=1&organization={request.POST.get("preview_org") or ""}')
        if action == 'publish':
            if not _can_publish_directly(request.user, item):
                from .models import ServiceCatalogChange
                from .service_requests import legacy_fields_from_schema
                ServiceCatalogChange.objects.create(
                    catalog_item=item, proposed_by=request.user,
                    before_snapshot={'form_schema': item.form_schema, 'fields_json': item.fields_json},
                    after_snapshot={'form_schema': schema,
                                    'fields_json': legacy_fields_from_schema(schema)},
                    reason=(request.POST.get('note') or 'Form builder change').strip()[:2000],
                )
                _audit(request, item, 'create', f'Proposed a new form for "{item.name}" (governance)')
                messages.success(request, 'This request type needs approval for changes: your form '
                                          'was filed as a change proposal.')
                return redirect('psa:catalog_change_list')
            version = request_forms.publish(item, request.user, schema=schema,
                                            note=(request.POST.get('note') or '').strip())
            _audit(request, item, 'update',
                   f'Published form v{version.number} of request type "{item.name}"',
                   {'version': version.number, 'fields': len(schema)})
            messages.success(request, f'Published version {version.number}. Customers filling in an '
                                      f'older version are asked to check their answers before sending.')
            return redirect('psa:request_type_builder', pk=item.pk)
        _audit(request, item, 'update', f'Saved a draft form for "{item.name}"', {'fields': len(schema)})
        messages.success(request, 'Draft saved. Customers still see the published form until you publish.')
        return redirect('psa:request_type_builder', pk=item.pk)
    return render(request, 'psa/request_types/builder.html', _builder_context(item, request.user))


class _PreviewMembership:
    """Stand-in membership for the staff preview: not an admin, no user."""
    is_org_admin = False
    is_active = True

    def __init__(self, organization):
        self.organization = organization
        self.organization_id = getattr(organization, 'pk', None)


@login_required
@require_psa_enabled
def request_type_preview(request, pk):
    """The customer's view of the form (draft or published), rendered with
    the portal template. Submitting is disabled; lookups are not run."""
    from core.models import Organization
    from portal.request_views import build_fields
    from .service_requests import FormContext, initial_values
    item = _item_for(request, pk)
    use_draft = request.GET.get('draft') == '1'
    schema = request_forms.draft_or_live_schema(item) if use_draft else item.get_form_schema()
    org = item.organization
    org_id = _int_or_none(request.GET.get('organization'))
    if org is None and org_id:
        org = Organization.objects.filter(pk=org_id, is_active=True).first()
        if org is not None and not request_forms.staff_may_manage(request.user, organization=org):
            org = None
    ctx = FormContext(organization=org, user=None, membership=_PreviewMembership(org)) if org else None
    return render(request, 'portal/request_form.html', {
        'organization': org, 'item': item,
        'fields': build_fields(schema, initial_values(schema), ctx, preview=True),
        'schema': schema, 'errors': [], 'notice': '', 'form_version': '',
        'submission_token': '', 'has_files': False, 'kb_suggestions': [],
        'preview': True, 'preview_draft': use_draft,
        'preview_back_url': reverse('psa:request_type_builder', args=[item.pk]),
    })


@login_required
@require_psa_enabled
def request_type_routing_preview(request, pk):
    """Which routing rule would match a request of this type with the given
    answers, for a chosen customer. Reads only: nothing is saved, no turn is
    used, nothing is sent."""
    from core.models import Organization
    from psa.models import TicketStatus
    from psa.routing import engine
    from psa.routing.permissions import PERM_TEST, has_routing_perm
    item = _item_for(request, pk)
    if not (request.user.is_superuser or has_routing_perm(request.user, PERM_TEST)):
        raise PermissionDenied('Testing routing needs the "Test routing" permission.')
    org = Organization.objects.filter(pk=_int_or_none(request.GET.get('organization')) or 0,
                                      is_active=True).first() or item.organization
    if org is None or not request_forms.staff_may_manage(request.user, organization=org):
        messages.error(request, 'Choose a customer you can see.')
        return redirect('psa:request_type_builder', pk=item.pk)
    rows = []
    schema = {f['key']: f for f in item.get_form_schema()}
    for line in (request.GET.get('answers') or '').splitlines()[:40]:
        if '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip()
        if k in schema:
            rows.append({'key': k, 'type': schema[k]['type'], 'value': v.strip()[:200]})
    ticket = Ticket(
        organization=org, subject=item.name, description='', source='portal',
        queue=item.default_queue or Queue.objects.filter(is_active=True).first(),
        priority=item.default_priority or TicketPriority.objects.order_by('sort_order').first(),
        ticket_type=item.default_type or TicketType.objects.filter(is_active=True).first(),
        status=TicketStatus.objects.filter(slug='new').first(),
        custom_fields={'service_request': {'catalog_item_slug': item.slug, 'answers': rows}},
    )
    with transaction.atomic():
        result = engine.evaluate(ticket, ignore_mode=True)
        mode = engine.effective_mode(org)[0]
        transaction.set_rollback(True)
    return render(request, 'psa/request_types/routing_preview.html', {
        'item': item, 'organization': org, 'result': result, 'rows': rows,
        'answers_text': request.GET.get('answers') or '', 'mode': mode,
        'default_queue': ticket.queue,
    })


# ---------------------------------------------------------------------------
# Request answers on a ticket (staff)
# ---------------------------------------------------------------------------

def can_edit_answers(user, ticket):
    from accounts.permission_utils import has_perm_for_org
    from psa.visibility import is_msp_staff
    return bool(is_msp_staff(user) and has_perm_for_org(user, ticket.organization_id, 'tickets_edit'))


EDITABLE_TYPES = ('text', 'textarea', 'email', 'tel', 'number', 'date', 'select', 'radio',
                  'multiselect', 'checkbox', 'user')


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def ticket_request_answers_edit(request, ticket_number):
    """Correct a submitted answer. Validated against the form version the
    customer submitted; the original answers stay on the submission record
    and every change is in the audit log."""
    from .service_requests import (
        SERVICE_REQUEST_KEY, _clean_value, answers_as_rows, option_pairs,
    )
    from .views import _scoped_ticket_qs
    ticket = get_object_or_404(_scoped_ticket_qs(request), ticket_number=ticket_number)
    if not can_edit_answers(request.user, ticket):
        raise PermissionDenied()
    record = (ticket.custom_fields or {}).get(SERVICE_REQUEST_KEY)
    if not isinstance(record, dict):
        raise Http404()
    sub = ServiceRequestSubmission.objects.filter(ticket=ticket).select_related('form_version').first()
    if sub is not None and sub.form_version is not None:
        schema = list(sub.form_version.schema)
    elif sub is not None and sub.schema_snapshot:
        schema = list(sub.schema_snapshot)
    else:
        schema = [{'key': r['key'], 'label': r['label'], 'type': r.get('type', 'text')}
                  for r in record.get('answers') or [] if isinstance(r, dict)]
    by_key = {r.get('key'): r for r in record.get('answers') or [] if isinstance(r, dict)}
    editable = [f for f in schema if f['type'] in EDITABLE_TYPES and f['key'] in by_key]

    if request.method == 'POST':
        changes, errors = [], []
        answers = {k: r.get('value') for k, r in by_key.items() if r.get('type') != 'heading'}
        for f in editable:
            if ('f_' + f['key']) not in request.POST and f['type'] not in ('checkbox', 'multiselect'):
                continue
            value, err = _clean_value(f, request.POST)
            if err:
                errors.append(err)
                continue
            if value != answers.get(f['key']):
                changes.append({'key': f['key'], 'label': f['label'],
                                'before': by_key[f['key']].get('display'),
                                'after': value})
                answers[f['key']] = value
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect(request.path)
        if changes:
            ordered = [f for f in schema if f['key'] in answers or f['type'] == 'heading']
            rows = answers_as_rows(ordered, answers)
            for c in changes:
                c['after'] = next((r['display'] for r in rows if r['key'] == c['key']), '')
            record['answers'] = rows
            record['edited_at'] = timezone.now().strftime('%Y-%m-%d %H:%M')
            record['edited_by_id'] = request.user.pk
            cf = dict(ticket.custom_fields or {})
            cf[SERVICE_REQUEST_KEY] = record
            ticket.custom_fields = cf
            ticket.updated_by = request.user
            ticket.save(update_fields=['custom_fields', 'updated_at', 'updated_by'])
            if sub is not None:
                sub.answers = rows
                sub.edited_at = timezone.now()
                sub.edited_by = request.user
                sub.save(update_fields=['answers', 'edited_at', 'edited_by'])
            from .models import TicketComment
            TicketComment.objects.create(
                ticket=ticket, is_internal=True, is_system=True, source='workflow',
                author=request.user,
                body='Request details edited: ' + ', '.join(c['label'] for c in changes) + '.',
            )
            AuditLog.log(
                user=request.user, action='update', organization=ticket.organization,
                object_type='psa.Ticket', object_id=ticket.pk, object_repr=ticket.ticket_number,
                description=f'Edited request answers on {ticket.ticket_number}: '
                            + ', '.join(c['label'] for c in changes),
                ip_address=_ip(request), path=request.path,
                extra_data={'changes': [{'key': c['key'], 'before': c['before'], 'after': c['after']}
                                        for c in changes]},
            )
            messages.success(request, f'Updated {len(changes)} answer(s).')
        else:
            messages.info(request, 'No changes.')
        return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)

    fields = []
    for f in editable:
        fd = dict(f)
        fd['current'] = by_key[f['key']].get('value')
        if f['type'] in ('select', 'radio', 'multiselect'):
            fd['pairs'] = option_pairs(f)
        fields.append(fd)
    return render(request, 'psa/request_types/answers_edit.html', {
        'ticket': ticket, 'record': record, 'fields': fields,
        'readonly_rows': [r for k, r in by_key.items()
                          if r.get('type') != 'heading' and k not in {f['key'] for f in editable}],
    })


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
def request_type_report(request):
    """Requests per request type (and per status bucket), optionally for one
    customer and a date range. CSV with ?format=csv."""
    _require_admin(request)
    from accounts.permission_utils import orgs_with_perm
    from datetime import date, timedelta
    try:
        start = date.fromisoformat(request.GET.get('from') or '')
    except ValueError:
        start = timezone.localdate() - timedelta(days=90)
    try:
        end = date.fromisoformat(request.GET.get('to') or '')
    except ValueError:
        end = timezone.localdate()
    qs = ServiceRequestSubmission.objects.filter(ticket__isnull=False,
                                                 created_at__date__gte=start, created_at__date__lte=end)
    allowed = orgs_with_perm(request.user, 'tickets_view')
    if allowed is not None:
        qs = qs.filter(organization_id__in=allowed)
    org_id = _int_or_none(request.GET.get('organization'))
    if org_id:
        qs = qs.filter(organization_id=org_id)
    rows = list(qs.values('catalog_item_id', 'catalog_item_name')
                .annotate(total=Count('pk'),
                          open=Count('pk', filter=Q(ticket__status__is_terminal=False)),
                          closed=Count('pk', filter=Q(ticket__status__is_terminal=True)))
                .order_by('-total', 'catalog_item_name'))
    if request.GET.get('format') == 'csv':
        import csv
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="request-types-{start}-{end}.csv"'
        w = csv.writer(resp)
        w.writerow(['Request type', 'Requests', 'Open', 'Closed'])
        for r in rows:
            name = r['catalog_item_name'] or '(deleted request type)'
            if name[:1] in ('=', '+', '-', '@'):
                name = "'" + name
            w.writerow([name, r['total'], r['open'], r['closed']])
        return resp
    from core.models import Organization
    orgs = Organization.objects.filter(is_active=True).order_by('name')
    if allowed is not None:
        orgs = orgs.filter(pk__in=allowed)
    return render(request, 'psa/request_types/report.html', {
        'rows': rows, 'start': start, 'end': end, 'organizations': orgs, 'org_id': org_id,
        'total': sum(r['total'] for r in rows),
    })
