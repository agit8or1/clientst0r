"""Support workflow pages: a ticket's workflows, one run, and the admin list."""
from __future__ import annotations

import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from psa.feature_flags import require_psa_enabled
from psa.routing.permissions import PERM_MANAGE, require_routing_perm

from . import engine
from .builtins import BUILTINS
from .models import SupportWorkflowDefinition, WorkflowRun


def _ticket_for(request, ticket_number):
    from psa.models import Ticket
    ticket = Ticket.objects.select_related('organization', 'related_asset').filter(ticket_number=ticket_number).first()
    if ticket is None or not engine.can_view(request.user, ticket):
        raise Http404
    return ticket


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def ticket_workflows(request, ticket_number):
    ticket = _ticket_for(request, ticket_number)
    if request.method == 'POST':
        try:
            link_id = int(request.POST.get('link') or 0) or None
        except ValueError:
            link_id = None
        try:
            run = engine.start(request.user, ticket, (request.POST.get('workflow') or '')[:64], link_id=link_id,
                               request=request)
        except engine.WorkflowRefused as e:
            messages.error(request, e.message)
            return redirect('support_workflows:ticket', ticket_number=ticket.ticket_number)
        return redirect('support_workflows:run', run_id=run.pk)
    from psa.routing.alert_policy import links_for_ticket
    return render(request, 'support_workflows/ticket.html', {
        'ticket': ticket, 'options': engine.for_ticket(ticket), 'links': links_for_ticket(ticket),
        'runs': WorkflowRun.objects.filter(ticket=ticket).select_related('actor')[:20],
        'can_run': engine.can_run(request.user, ticket),
    })


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def run_detail(request, run_id):
    run = get_object_or_404(WorkflowRun.objects.select_related('ticket', 'ticket__organization', 'actor',
                                                               'alert_link', 'device', 'rmm_request'), pk=run_id)
    if not engine.can_view(request.user, run.ticket):
        raise Http404
    if request.method == 'POST':
        op = request.POST.get('op')
        try:
            if op == 'propose':
                engine.propose(request.user, run, (request.POST.get('action') or '')[:64],
                               (request.POST.get('key') or '')[:64], request=request)
                messages.success(request, 'Sent to Rem0te for approval. Nothing runs until its approvers approve it.')
            elif op == 'manual':
                engine.manual_done(request.user, run, request.POST.get('note') or '', request=request)
                messages.success(request, 'Recorded. Monitoring now has to confirm the fix.')
            elif op == 'diagnostic':
                engine.request_diagnostic(request.user, run, (request.POST.get('diagnostic') or '')[:64],
                                          (request.POST.get('key') or '')[:64], request=request)
                messages.success(request, 'Read-only diagnostic requested.')
            elif op == 'refresh':
                if not engine.can_run(request.user, run.ticket):
                    raise engine.WorkflowRefused('You may not work on this ticket.')
                engine.refresh(run, force=True)
            elif op == 'cancel':
                engine.cancel(request.user, run)
        except engine.WorkflowRefused as e:
            messages.error(request, e.message)
        return redirect('support_workflows:run', run_id=run.pk)
    from psa_ai.models import RMMRequest
    run.refresh_from_db()
    can = engine.can_run(request.user, run.ticket)
    return render(request, 'support_workflows/run.html', {
        'run': run, 'ticket': run.ticket, 'can_run': can,
        'can_propose': can and run.status in engine.PROPOSABLE_FROM,
        'can_manual': can and run.status in engine.MANUAL_FROM,
        'request_key': uuid.uuid4().hex[:32],
        'diagnostic_requests': RMMRequest.objects.filter(ticket=run.ticket, kind=RMMRequest.KIND_DIAGNOSTIC,
                                                         created_at__gte=run.created_at)[:10],
    })


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def admin_list(request):
    if request.method == 'POST':
        slug = (request.POST.get('slug') or '')[:64]
        row = SupportWorkflowDefinition.objects.filter(slug=slug).first()
        if request.POST.get('op') == 'reset' and row is not None:
            row.delete()
            _audit(request, 'delete', slug, f'Support workflow "{slug}" reset to built-in / removed')
            messages.success(request, 'Workflow reset.')
        elif request.POST.get('op') == 'toggle':
            if row is None:
                b = engine.builtin(slug)
                if b is None:
                    raise Http404
                row = SupportWorkflowDefinition(slug=slug, name=b['name'], description=b.get('description', ''),
                                                definition={k: v for k, v in b.items() if k != 'slug'})
                row.is_active = True
            row.is_active = not row.is_active
            row.updated_by = request.user
            row.save()
            _audit(request, 'update', slug, f'Support workflow "{slug}" {"enabled" if row.is_active else "disabled"}')
        return redirect('support_workflows:admin')
    return render(request, 'support_workflows/admin.html', {
        'definitions': engine.definitions(include_inactive=True),
        'builtin_slugs': {b['slug'] for b in BUILTINS},
    })


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def admin_edit(request, slug=None):
    from django.utils.text import slugify
    row = SupportWorkflowDefinition.objects.filter(slug=slug).first() if slug else None
    current = (dict(row.definition) if row else (engine.builtin(slug) if slug else None))
    if slug and current is None:
        raise Http404
    errors = []
    text = json.dumps({k: v for k, v in (current or {
        'name': '', 'description': '', 'categories': ['other'], 'freshness_minutes': 30,
        'evidence': ['alert', 'device_status'], 'causes': [], 'remediations': [], 'manual_steps': [],
        'verify_within_minutes': 60}).items() if k != 'slug'}, indent=2)
    if request.method == 'POST':
        text = request.POST.get('definition') or ''
        new_slug = slug or slugify(request.POST.get('slug') or '')[:64]
        try:
            data = json.loads(text)
        except ValueError as e:
            data, errors = None, [f'Not valid JSON: {e}']
        if data is not None:
            errors = engine.validate_definition(data)
        if not new_slug:
            errors.append('A slug is required.')
        elif not slug and (engine.builtin(new_slug) or SupportWorkflowDefinition.objects.filter(slug=new_slug).exists()):
            errors.append('That slug is taken.')
        if not errors:
            data.pop('slug', None)
            obj, _ = SupportWorkflowDefinition.objects.update_or_create(
                slug=new_slug, defaults={'name': str(data['name'])[:120],
                                         'description': str(data.get('description') or '')[:300],
                                         'definition': data, 'updated_by': request.user})
            _audit(request, 'update', new_slug, f'Support workflow "{new_slug}" saved')
            messages.success(request, 'Workflow saved. Runs already started keep the version they started with.')
            return redirect('support_workflows:admin')
    from integrations.rem0te.pairing import KNOWN_ACTIONS
    return render(request, 'support_workflows/admin_edit.html', {
        'slug': slug, 'text': text, 'errors': errors, 'is_builtin': bool(slug and engine.builtin(slug)),
        'evidence_keys': engine.EVIDENCE, 'facts': sorted(engine.FACTS), 'ops': sorted(engine.OPS),
        'categories': sorted(engine.CATEGORIES), 'known_actions': KNOWN_ACTIONS,
    })


def _audit(request, action, slug, description):
    AuditLog.log(user=request.user, action=action, object_type='support_workflows.SupportWorkflowDefinition',
                 object_repr=slug[:200], description=description[:1000], path=request.path)
