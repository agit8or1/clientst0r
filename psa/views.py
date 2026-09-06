"""
PSA staff-side views.

Phase 1: list + detail + minimal create — enough to exercise the feature
flag gating, RBAC integration, audit logging, and tenant scoping. Phase 2
will flesh out merge/split, macros, canned replies, etc.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from core.decorators import require_admin, require_write
from core.middleware import get_request_organization
from vault.models import Password
from inventory.models import InventoryItem, Tool

from .feature_flags import (
    is_psa_enabled,
    is_psa_enabled_for_client,
    require_client_psa_enabled,
    require_psa_enabled,
)
from .models import (
    CannedReply,
    ClientPSASettings,
    Contract,
    EmailIngestionConfig,
    Project,
    PSAApproval,
    Queue,
    Quote,
    QuoteLineItem,
    RecurringTicketSchedule,
    ServiceCatalogItem,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketExpense,
    TicketKBLink,
    TicketPriority,
    TicketStatus,
    TicketTimeEntry,
    TicketType,
    TicketWatcher,
)
from .sla import apply_due_dates, hygiene_flags, status_chip

logger = logging.getLogger('psa.views')


# Phase 2a constants
ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024  # 25 MB
ATTACHMENT_ALLOWED_MIMES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml',
    'text/plain', 'text/csv', 'text/markdown',
    'application/json',
    'application/zip',
}


def _scoped_ticket_qs(request):
    """
    Tickets visible to the current request — PSA is now a global tool.

      * superuser / staff_user → every ticket across every client
      * org user               → only tickets for orgs they're a member of
        (regardless of which org they have currently "selected" — the PSA
        page is global, internal filtering replaces per-page client scoping)
    """
    qs = Ticket.objects.select_related(
        'organization', 'status', 'priority', 'queue', 'ticket_type', 'assigned_to'
    )
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        return qs
    if hasattr(request.user, 'memberships'):
        org_ids = list(
            request.user.memberships.filter(is_active=True).values_list('organization_id', flat=True)
        )
        return qs.filter(organization_id__in=org_ids)
    return qs.none()


@login_required
@require_psa_enabled
def ticket_list(request):
    """
    Global ticket list with internal filtering. Filters are URL params:
      ?client=<org_id>&status=<status_id>&priority=<priority_id>
      &queue=<queue_id>&assigned=<user_id|me|unassigned>&q=<text>
    """
    qs = _scoped_ticket_qs(request)

    # Filters
    client_id = request.GET.get('client') or ''
    status_id = request.GET.get('status') or ''
    priority_id = request.GET.get('priority') or ''
    queue_id = request.GET.get('queue') or ''
    assigned = request.GET.get('assigned') or ''
    search = (request.GET.get('q') or '').strip()

    if client_id:
        qs = qs.filter(organization_id=client_id)
    if status_id:
        qs = qs.filter(status_id=status_id)
    if priority_id:
        qs = qs.filter(priority_id=priority_id)
    if queue_id:
        qs = qs.filter(queue_id=queue_id)
    if assigned == 'me':
        qs = qs.filter(assigned_to=request.user)
    elif assigned == 'unassigned':
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned.isdigit():
        qs = qs.filter(assigned_to_id=int(assigned))
    if search:
        from django.db.models import Q
        qs = qs.filter(Q(ticket_number__icontains=search) | Q(subject__icontains=search))

    # Bound the page; full pagination is Phase 2 polish
    tickets = qs.order_by('-created_at')[:200]

    # Filter dropdown options — limited to what makes sense for the user.
    # For org-bound users, the client filter only shows their member orgs.
    from core.models import Organization
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        available_clients = Organization.objects.filter(is_active=True).order_by('name')
    elif hasattr(request.user, 'memberships'):
        ids = request.user.memberships.filter(is_active=True).values_list('organization_id', flat=True)
        available_clients = Organization.objects.filter(id__in=list(ids), is_active=True).order_by('name')
    else:
        available_clients = Organization.objects.none()

    return render(request, 'psa/ticket_list.html', {
        'tickets': tickets,
        'available_clients': available_clients,
        'available_statuses': TicketStatus.objects.all(),
        'available_priorities': TicketPriority.objects.all(),
        'available_queues': Queue.objects.filter(is_active=True),
        'filter_values': {
            'client': client_id, 'status': status_id, 'priority': priority_id,
            'queue': queue_id, 'assigned': assigned, 'q': search,
        },
        'has_filters': any([client_id, status_id, priority_id, queue_id, assigned, search]),
    })


@login_required
@require_psa_enabled
def ticket_detail(request, ticket_number):
    org = get_request_organization(request)
    qs = _scoped_ticket_qs(request)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)
    # If the requester's active org doesn't match the ticket's org and the
    # user is not staff/superuser, refuse — defence-in-depth.
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        if ticket.organization_id != getattr(org, 'id', None):
            raise Http404("Ticket not found")

    vault_qs = Password.objects.filter(
        organization=ticket.organization,
        is_personal=False,
    )
    vault_entries = vault_qs.only('id', 'title', 'username', 'updated_at')[:5]
    vault_count = vault_qs.count()

    is_closed = bool(ticket.closed_at) or (ticket.status_id and ticket.status.is_terminal)

    # Phase 2b — watchers + canned replies
    watchers_count = ticket.watchers.count()
    is_watcher = ticket.watchers.filter(user=request.user).exists()

    # Phase 2c — SLA + time + hygiene + similar tickets (recurring detect)
    sla = status_chip(ticket)
    hygiene = hygiene_flags(ticket)
    time_entries = list(ticket.time_entries.select_related('user').order_by('-started_at')[:30])
    running_timer = ticket.time_entries.filter(user=request.user, ended_at__isnull=True).first()
    total_minutes = sum(te.duration_minutes for te in time_entries)
    billable_minutes = sum(te.duration_minutes for te in time_entries if te.is_billable)

    from psa.sla import find_similar_tickets
    similar = find_similar_tickets(ticket)

    # Phase 4 — surface the active client contract on the ticket
    contract = Contract.for_ticket(ticket)

    # Phase 5 — list expenses on the ticket (most recent first)
    expenses = list(ticket.expenses.select_related('user').order_by('-incurred_on')[:30])
    total_expense = sum(float(e.amount) for e in expenses if e.is_billable)

    # Canned replies visible for this ticket: global ones + ones scoped to the
    # ticket's client. Pre-render each so the template can drop the result
    # into the textarea on click without a round-trip.
    canned = (
        CannedReply.objects
        .filter(is_active=True)
        .filter(models.Q(organization__isnull=True) | models.Q(organization=ticket.organization))
        .order_by('sort_order', 'name')
    )
    canned_replies = [
        {'id': c.id, 'name': c.name, 'rendered': c.render(ticket=ticket, user=request.user)}
        for c in canned
    ]

    # Phase 10a — surface AI suggestions on the ticket
    ai_suggestions = []
    ai_suggestions_json = []
    ai_enabled = False
    try:
        from core.models import SystemSetting
        from psa_ai.models import AISuggestion
        ss = SystemSetting.get_settings()
        ai_enabled = bool(ss.psa_ai_enabled)
        if ai_enabled:
            ai_suggestions = list(
                AISuggestion.objects
                .filter(native_ticket=ticket)
                .order_by('-created_at')[:10]
            )
            ai_suggestions_json = [
                {'id': s.id, 'suggested_body': s.suggested_body}
                for s in ai_suggestions
            ]
    except Exception:
        ai_enabled = False

    # The most recent triage suggestion is rendered expanded with the
    # full warning banner; older triages collapse into <details> blocks.
    ai_latest_triage_id = None
    for _s in ai_suggestions:
        if getattr(_s, 'kind', '') == 'triage':
            ai_latest_triage_id = _s.id
            break

    # Workflow executions tied to this ticket (Operations → Workflows)
    # Eager-load stage completions so the ticket detail page can render the
    # full inline stage checklist without N+1 queries.
    workflow_executions = []
    try:
        from django.db.models import Prefetch
        from processes.models import (
            ProcessExecution, ProcessStageCompletion, ProcessExecutionAuditLog,
        )
        workflow_executions = list(
            ProcessExecution.objects.filter(native_psa_ticket=ticket)
            .select_related('process', 'assigned_to', 'started_by')
            .prefetch_related(
                Prefetch(
                    'stage_completions',
                    queryset=ProcessStageCompletion.objects.select_related(
                        'stage',
                        'stage__linked_document',
                        'stage__linked_password',
                        'stage__linked_secure_note',
                        'stage__linked_asset',
                        'completed_by',
                    ).order_by('stage__order'),
                ),
                # Recent audit-log entries (sign-off history) so the ticket
                # detail page can render an inline timeline of stage events.
                Prefetch(
                    'audit_logs',
                    queryset=ProcessExecutionAuditLog.objects
                    .select_related('user', 'stage')
                    .order_by('-created_at')[:25],
                    to_attr='recent_audit_logs',
                ),
            )
            .order_by('-created_at')[:10]
        )
    except Exception:
        pass

    # v3.17.129 — admin-only "Assign to tech" sub-menu in the Actions dropdown.
    can_assign = _can_assign(request, ticket.organization)
    eligible_assignees = _eligible_assignees(ticket.organization) if can_assign else []

    # Phase 6.2 — surface linked Problem records (the M2M reverse).
    problems = list(ticket.problems.all().order_by('-created_at'))
    from accounts.permission_utils import user_has_perm as _uhp
    problem_can_create = _uhp(request.user, 'problem_create')

    kit_items = list(ticket.kit_items.select_related(
        'tool', 'inventory_item', 'packed_by').all())

    return render(request, 'psa/ticket_detail.html', {
        'ticket': ticket,
        'workflow_executions': workflow_executions,
        'comments': ticket.comments.select_related('author').order_by('created_at'),
        'attachments': ticket.attachments.select_related('uploaded_by').order_by('-created_at'),
        'vault_entries': vault_entries,
        'vault_count': vault_count,
        'available_statuses': TicketStatus.objects.all(),
        'closure_categories': Ticket.CLOSURE_CATEGORIES,
        'is_closed': is_closed,
        'attachment_max_mb': ATTACHMENT_MAX_BYTES // (1024 * 1024),
        'watchers_count': watchers_count,
        'is_watcher': is_watcher,
        'canned_replies': canned_replies,
        'ai_enabled': ai_enabled,
        'ai_suggestions': ai_suggestions,
        'ai_suggestions_json': ai_suggestions_json,
        'ai_latest_triage_id': ai_latest_triage_id,
        'sla': sla,
        'hygiene': hygiene,
        'time_entries': time_entries,
        'running_timer': running_timer,
        'total_minutes': total_minutes,
        'billable_minutes': billable_minutes,
        'similar_tickets': similar,
        'contract': contract,
        'expenses': expenses,
        'total_expense_billable': total_expense,
        'expense_categories': TicketExpense.CATEGORY_CHOICES,
        'can_assign': can_assign,
        'eligible_assignees': eligible_assignees,
        # Phase 6.2 — Problem records linked to this ticket
        'problems': problems,
        'problem_can_create': problem_can_create,
        # Phase 46 (v3.17.533): what the tech has to take to this job.
        'kit_items': kit_items,
        'kit_packed_count': sum(1 for k in kit_items if k.packed),
        'kit_tools': Tool.objects.for_organization(
            ticket.organization).filter(is_active=True),
        'kit_inventory': InventoryItem.objects.for_organization(
            ticket.organization),
    })


@login_required
@require_psa_enabled
def ticket_conversation(request, ticket_number):
    """
    Phase 10.4: per-ticket email conversation panel.

    Lists every captured ``EmailMessage`` row for the ticket — inbound
    polled mail (10.1), outbound threaded replies sent via
    ``email_outbound.send_threaded_reply`` (10.4), in chronological order.
    HTML body renders inside a sandboxed iframe so any residual markup
    after sanitization can't escape.

    Same tenant-isolation rules as ``ticket_detail``: org users only see
    their own org's tickets; superusers / staff see anything.
    """
    from .models import EmailMessage

    org = get_request_organization(request)
    qs = _scoped_ticket_qs(request)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        if ticket.organization_id != getattr(org, 'id', None):
            raise Http404('Ticket not found')

    messages_qs = (
        EmailMessage.objects
        .filter(ticket=ticket)
        .order_by('received_at')
    )
    return render(request, 'psa/ticket_conversation.html', {
        'ticket': ticket,
        'email_messages': messages_qs,
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def ticket_create(request):
    """
    Create a ticket. The client/organization is chosen from a dropdown in
    the form (filtered to clients without an active external PSA — the
    hard rule). PSA is global; we don't depend on `current_organization`.
    """
    from psa.feature_flags import clients_eligible_for_native_psa
    queues = Queue.objects.filter(is_active=True)
    statuses = TicketStatus.objects.all()
    priorities = TicketPriority.objects.all()
    types = TicketType.objects.filter(is_active=True)
    eligible_clients = clients_eligible_for_native_psa(request.user)

    # If the user has zero eligible clients, we can't proceed — show a
    # friendly dead end (every client they could pick has an external PSA,
    # OR they have no memberships at all).
    if not eligible_clients.exists():
        return render(request, 'psa/ticket_create.html', {
            'queues': [], 'statuses': [], 'priorities': [], 'types': [],
            'eligible_clients': eligible_clients,
            'no_eligible_clients': True,
        })

    if request.method == 'POST':
        # If a catalog template was used, harvest the dynamic field values
        # and render the subject/body templates.
        catalog_slug = request.POST.get('catalog_slug') or ''
        catalog_post = ServiceCatalogItem.objects.filter(slug=catalog_slug, is_active=True).first() if catalog_slug else None

        if catalog_post is not None:
            values = {}
            missing = []
            for f in (catalog_post.fields_json or []):
                key = f.get('key') or ''
                if not key:
                    continue
                # Checkbox = "on"/None → "yes"/"no"; everything else is text-like.
                if f.get('type') == 'checkbox':
                    raw = (request.POST.get(f'field_{key}') or '').lower()
                    values[key] = 'yes' if raw in ('1', 'true', 'on', 'yes') else 'no'
                else:
                    raw = (request.POST.get(f'field_{key}') or '').strip()
                    values[key] = raw
                    if f.get('required') and not raw:
                        missing.append(f.get('label') or key)
            if missing:
                messages.error(request, 'Required field(s) missing: ' + ', '.join(missing))
                return redirect(reverse('psa:ticket_create') + f'?from_catalog={catalog_slug}')
            subject = ServiceCatalogItem.render_template(catalog_post.default_subject, values).strip()
            description = ServiceCatalogItem.render_template(catalog_post.default_body, values).strip()
        else:
            subject = (request.POST.get('subject') or '').strip()
            description = (request.POST.get('description') or '').strip()

        client_id = request.POST.get('client') or ''
        if not subject:
            messages.error(request, 'Subject is required.')
            return redirect(reverse('psa:ticket_create'))
        if not client_id:
            messages.error(request, 'Please pick a client for this ticket.')
            return redirect(reverse('psa:ticket_create'))

        try:
            org = eligible_clients.get(pk=client_id)
        except Exception:
            messages.error(request, 'That client is not eligible for native PSA tickets.')
            return redirect(reverse('psa:ticket_create'))

        try:
            queue = queues.get(pk=request.POST.get('queue'))
            status = statuses.get(pk=request.POST.get('status'))
            priority = priorities.get(pk=request.POST.get('priority'))
            ticket_type = types.get(pk=request.POST.get('ticket_type'))
        except (Queue.DoesNotExist, TicketStatus.DoesNotExist,
                TicketPriority.DoesNotExist, TicketType.DoesNotExist):
            messages.error(request, 'Invalid queue/status/priority/type selection.')
            return redirect(reverse('psa:ticket_create'))

        # v3.17.129 — admin-only "Assign to" picker on ticket creation.
        # The form may post `assigned_to`; only honour it when the requester
        # has permission to assign work in this org AND the target is
        # eligible (org member, or staff/superuser).
        initial_assignee = None
        posted_assignee = (request.POST.get('assigned_to') or '').strip()
        if posted_assignee and _can_assign(request, org):
            from django.contrib.auth.models import User
            try:
                cand = User.objects.get(pk=int(posted_assignee), is_active=True)
                eligible_ids = set(_eligible_assignees(org).values_list('id', flat=True))
                if cand.id in eligible_ids:
                    initial_assignee = cand
            except (User.DoesNotExist, ValueError, TypeError):
                pass

        ticket = Ticket.objects.create(
            organization=org,
            subject=subject,
            description=description,
            queue=queue,
            status=status,
            priority=priority,
            ticket_type=ticket_type,
            source='manual',
            created_by=request.user,
            updated_by=request.user,
            assigned_to=initial_assignee,
        )
        # Compute SLA due-dates from the priority's targets
        apply_due_dates(ticket)

        AuditLog.log(
            user=request.user,
            action='create',
            organization=org,
            object_type='psa.Ticket',
            object_id=ticket.pk,
            object_repr=ticket.ticket_number,
            description=f'Created PSA ticket {ticket.ticket_number}: {ticket.subject[:120]}',
            ip_address=_client_ip(request),
            path=request.path,
        )

        # Optional workflow attachment — if the user picked a Process template,
        # spawn a ProcessExecution linked to the new ticket and seed the stage
        # completions so the embedded checklist appears immediately.
        workflow_id = (request.POST.get('workflow_id') or '').strip()
        if workflow_id:
            try:
                from processes.models import (
                    Process, ProcessExecution, ProcessStageCompletion,
                    ProcessExecutionAuditLog,
                )
                process = Process.objects.filter(
                    pk=int(workflow_id), is_published=True, is_archived=False,
                ).first()
                if process is not None:
                    execution = ProcessExecution.objects.create(
                        process=process,
                        organization=org,
                        assigned_to=request.user,
                        started_by=request.user,
                        status='in_progress',
                        started_at=timezone.now(),
                        native_psa_ticket=ticket,
                        notes=f'Attached at ticket creation.',
                    )
                    for stage in process.stages.all().order_by('order'):
                        ProcessStageCompletion.objects.create(
                            execution=execution, stage=stage, is_completed=False,
                        )
                    ProcessExecutionAuditLog.log_action(
                        execution=execution,
                        action_type='execution_created',
                        user=request.user,
                        description=(
                            f"{request.user.username} attached workflow "
                            f"'{process.title}' at ticket creation"
                        ),
                        request=request,
                    )
            except (ValueError, TypeError):
                pass  # invalid workflow_id — silently ignore

        messages.success(request, f'Ticket {ticket.ticket_number} created.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    # Pre-select the active org if the user has one and it's eligible.
    preselected = get_request_organization(request)
    preselected_id = preselected.id if preselected and eligible_clients.filter(id=preselected.id).exists() else None

    # If invoked via /psa/new/?from_catalog=<slug>, pre-fill from the
    # service-catalog template
    catalog_slug = request.GET.get('from_catalog') or ''
    catalog_item = None
    if catalog_slug:
        catalog_item = ServiceCatalogItem.objects.filter(slug=catalog_slug, is_active=True).first()

    # Workflow templates available to attach at creation. List ALL published,
    # non-archived templates — the user picks one and the org is set when the
    # ticket is saved. (Earlier we tried to scope by current-org, but most
    # processes are tied to a specific org so the dropdown went empty in
    # Global view.)
    available_workflows = []
    try:
        from processes.models import Process
        available_workflows = list(
            Process.objects.filter(is_published=True, is_archived=False)
            .order_by('organization__name', 'title')
            .values('pk', 'title', 'organization_id', 'organization__name')
        )
    except Exception:
        pass

    # v3.17.129 — show the optional "Assign to" picker to org admins +
    # staff/superusers. At GET time we don't know which client the user will
    # pick, so we offer the union of eligible techs across every eligible
    # client. The save path re-validates against the chosen org.
    can_assign = (
        request.user.is_superuser
        or getattr(request, 'is_staff_user', False)
        or any(_can_assign(request, c) for c in eligible_clients)
    )
    eligible_assignees = []
    if can_assign:
        from django.contrib.auth.models import User
        client_ids = list(eligible_clients.values_list('id', flat=True))
        eligible_assignees = list(
            User.objects.filter(is_active=True)
            .filter(
                models.Q(is_staff=True) | models.Q(is_superuser=True)
                | models.Q(memberships__organization_id__in=client_ids,
                           memberships__is_active=True)
            )
            .distinct()
            .order_by('username')
        )

    return render(request, 'psa/ticket_create.html', {
        'queues': queues,
        'statuses': statuses,
        'priorities': priorities,
        'types': types,
        'eligible_clients': eligible_clients,
        'preselected_client_id': preselected_id,
        'no_eligible_clients': False,
        'catalog_item': catalog_item,
        'available_workflows': available_workflows,
        'can_assign': can_assign,
        'eligible_assignees': eligible_assignees,
    })


@login_required
@require_psa_enabled
def psa_global_settings_view(request):
    """
    Global PSA settings page. Replaces the previous per-client settings —
    per-surface flags now live on `core.SystemSetting` and apply to every
    client. Per-client manual opt-outs (rare; used to override the
    auto-detect that already excludes external-PSA clients) are listed
    here too with un-opt-out buttons.

    v3.17.244: tightened to superuser-only. Previously allowed
    `is_staff_user` too, which meant any MSP staff (not just admins)
    could mutate `SystemSetting` feature toggles. Now matches the
    pattern in `core/settings_views.py` where every settings_* view is
    `@user_passes_test(is_superuser)`.
    """
    if not request.user.is_superuser:
        raise Http404()

    from core.models import SystemSetting
    settings = SystemSetting.get_settings()

    # All explicit ClientPSASettings rows that are opt-OUTs (the only useful
    # use of the row in the global model — admin-disabled native PSA for
    # a specific client even though they have no external PSA).
    opt_outs = ClientPSASettings.objects.filter(enabled=False).select_related('organization')

    if request.method == 'POST':
        action = request.POST.get('action') or 'save_globals'

        if action == 'remove_opt_out':
            org_id = request.POST.get('organization_id') or ''
            cps = ClientPSASettings.objects.filter(organization_id=org_id, enabled=False).first()
            if cps is not None:
                cps_pk = cps.pk
                org_repr = str(cps.organization)
                cps.delete()
                AuditLog.log(
                    user=request.user, action='delete',
                    organization_id=int(org_id),
                    object_type='psa.ClientPSASettings', object_id=cps_pk,
                    object_repr=f'PSA opt-out removed for {org_repr}',
                    description='Removed PSA opt-out — client returns to auto-detect',
                    ip_address=_client_ip(request), path=request.path,
                )
                messages.success(request, f'Removed opt-out for {org_repr}.')
            return redirect('psa:settings')

        # Default: save global per-surface flags + AI behavior knobs
        previous = {
            'psa_portal_enabled': settings.psa_portal_enabled,
            'psa_anonymous_ticket_form_enabled': settings.psa_anonymous_ticket_form_enabled,
            'psa_email_to_ticket_enabled': settings.psa_email_to_ticket_enabled,
            'psa_sms_notifications_enabled': settings.psa_sms_notifications_enabled,
            'psa_desktop_alerts_enabled': settings.psa_desktop_alerts_enabled,
            'psa_external_alert_ingest_enabled': settings.psa_external_alert_ingest_enabled,
            'psa_ai_enabled': settings.psa_ai_enabled,
            'psa_ai_voice': settings.psa_ai_voice,
            'psa_ai_min_confidence': str(settings.psa_ai_min_confidence),
            'psa_ai_blocked_subject_keywords': settings.psa_ai_blocked_subject_keywords,
        }
        settings.psa_portal_enabled = request.POST.get('psa_portal_enabled') == 'on'
        settings.psa_anonymous_ticket_form_enabled = request.POST.get('psa_anonymous_ticket_form_enabled') == 'on'
        settings.psa_email_to_ticket_enabled = request.POST.get('psa_email_to_ticket_enabled') == 'on'
        settings.psa_sms_notifications_enabled = request.POST.get('psa_sms_notifications_enabled') == 'on'
        settings.psa_desktop_alerts_enabled = request.POST.get('psa_desktop_alerts_enabled') == 'on'
        settings.psa_external_alert_ingest_enabled = request.POST.get('psa_external_alert_ingest_enabled') == 'on'

        settings.psa_ai_enabled = request.POST.get('psa_ai_enabled') == 'on'
        settings.psa_ai_voice = (request.POST.get('psa_ai_voice') or '').strip()[:1000]
        try:
            from decimal import Decimal as _D
            v = _D(request.POST.get('psa_ai_min_confidence') or '0.75')
            if v < 0:
                v = _D('0')
            if v > 1:
                v = _D('1')
            settings.psa_ai_min_confidence = v
        except Exception:
            pass
        settings.psa_ai_blocked_subject_keywords = (
            request.POST.get('psa_ai_blocked_subject_keywords') or ''
        ).strip()[:5000]

        settings.updated_by = request.user
        settings.save()

        # Build the current snapshot with the SAME normalisation as `previous`
        # so the diff is like-for-like. `psa_ai_min_confidence` is a Decimal,
        # which (a) never compares equal to the stringified `previous` value —
        # so it always showed as "changed" — and (b) is not JSON-serialisable,
        # which crashed the AuditLog JSONField write with
        # "Object of type Decimal is not JSON serializable" (issue #141).
        # Stringifying both sides fixes the false diff and the crash.
        current = {k: getattr(settings, k) for k in previous}
        current['psa_ai_min_confidence'] = str(settings.psa_ai_min_confidence)
        changed = {k: (previous[k], current[k]) for k in previous if previous[k] != current[k]}
        AuditLog.log(
            user=request.user, action='update',
            object_type='core.SystemSetting',
            object_id=settings.pk, object_repr='Global PSA settings',
            description=f'Updated global PSA settings ({len(changed)} change(s))',
            ip_address=_client_ip(request), path=request.path,
            extra_data={'changed_fields': {k: {'from': v[0], 'to': v[1]} for k, v in changed.items()}},
        )
        messages.success(request, 'PSA global settings saved.')
        return redirect('psa:settings')

    return render(request, 'psa/global_settings.html', {
        'settings': settings,
        'opt_outs': opt_outs,
    })


# Backwards-compat shim: the old per-client URL still resolves but
# redirects to the new global page so any bookmarks keep working.
@login_required
@require_psa_enabled
def client_settings_view(request):
    return redirect('psa:settings')


@login_required
@require_psa_enabled
def ticket_vault_context(request, ticket_number):
    """
    Read-only metadata view of the ticket organization's vault entries.

    Renders titles + links to the existing vault detail page only — never
    inlines secret values or loads encrypted columns. The vault detail
    view enforces its own permission and audit checks when the tech opens
    an entry in a new tab.
    """
    org = get_request_organization(request)
    qs = _scoped_ticket_qs(request)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)
    # Defence-in-depth: non-staff users must be acting in the ticket's org.
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        if ticket.organization_id != getattr(org, 'id', None):
            raise Http404("Ticket not found")

    vault_entries = (
        Password.objects
        .filter(organization=ticket.organization, is_personal=False)
        .only('id', 'title', 'username', 'updated_at', 'organization_id')
        .order_by('title')
    )

    AuditLog.log(
        user=request.user,
        action='read',
        organization=ticket.organization,
        object_type='psa.TicketContext',
        object_id=ticket.pk,
        object_repr=ticket.ticket_number,
        description=f'Opened vault context for ticket {ticket.ticket_number}',
        ip_address=_client_ip(request),
        path=request.path,
    )

    return render(request, 'psa/ticket_vault_context.html', {
        'ticket': ticket,
        'vault_entries': vault_entries,
    })


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _scoped_ticket_for_write(request, ticket_number):
    """Resolve a ticket the user can write to (404 if outside their scope)."""
    qs = _scoped_ticket_qs(request)
    return get_object_or_404(qs, ticket_number=ticket_number)


# ---------------------------------------------------------------------------
# Phase 2a — comments / internal notes / attachments / quick actions / close
# ---------------------------------------------------------------------------

@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_post_comment(request, ticket_number):
    """Add a reply or internal note. POST: body, is_internal."""
    ticket = _scoped_ticket_for_write(request, ticket_number)
    body = (request.POST.get('body') or '').strip()
    if not body:
        messages.error(request, 'Comment cannot be empty.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    is_internal = (request.POST.get('is_internal') or '').lower() in ('1', 'true', 'on', 'yes')
    comment = TicketComment.objects.create(
        ticket=ticket, author=request.user,
        body=body, is_internal=is_internal, is_system=False,
    )

    now = timezone.now()
    update_fields = ['updated_by', 'updated_at', 'last_tech_response_at']
    ticket.updated_by = request.user
    ticket.last_tech_response_at = now
    if not ticket.first_response_at and not is_internal:
        ticket.first_response_at = now
        update_fields.append('first_response_at')
    ticket.save(update_fields=update_fields)

    AuditLog.log(
        user=request.user, action='create', organization=ticket.organization,
        object_type='psa.TicketComment', object_id=comment.pk,
        object_repr=f'{"internal note" if is_internal else "reply"} on {ticket.ticket_number}',
        description=f'Added {"internal note" if is_internal else "reply"} to {ticket.ticket_number}',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'is_internal': is_internal, 'length': len(body)},
    )
    # Notify watchers (best-effort; SMTP failures don't block the request).
    _notify_watchers(ticket, comment, request.user)
    # Parse @mentions, auto-add as watcher + notify.
    _process_mentions(ticket, comment, request.user)
    messages.success(request, 'Comment added.')

    # Issue #142 — opt-in: also send this reply to the requester as email,
    # via whichever transport the mailbox is configured for (SMTP or Graph).
    # Internal notes are never emailed. Send failures surface as a message but
    # never discard the comment that was already saved.
    send_email = (request.POST.get('send_email') or '').lower() in ('1', 'true', 'on', 'yes')
    if send_email and not is_internal:
        _email_reply_to_requester(request, ticket, comment)

    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


def _email_reply_to_requester(request, ticket, comment):
    """Email a public ticket reply to the requester (issue #142).

    Best-effort by design: the comment is already committed, so every failure
    path here reports through ``messages`` rather than raising. Graph sends
    return an ``EmailOutboundJob`` whose status distinguishes accepted from
    queued-for-retry from failed; SMTP returns the persisted ``EmailMessage``.
    """
    from psa.email_outbound import resolve_ticket_email_config, send_ticket_reply
    from psa.models import EmailOutboundJob

    if not ticket.requester_email:
        messages.warning(
            request,
            'Comment saved, but no email was sent — this ticket has no requester email address.')
        return

    try:
        config = resolve_ticket_email_config(ticket)
        result = send_ticket_reply(
            ticket=ticket, config=config, comment=comment,
            body_text=comment.body, created_by=request.user,
        )
    except Exception as exc:
        logger.warning('ticket reply email failed ticket=%s: %s', ticket.ticket_number, exc)
        messages.error(request, f'Comment saved, but the email could not be sent: {exc}')
        return

    if isinstance(result, EmailOutboundJob):
        if result.status == EmailOutboundJob.STATUS_SENT:
            outcome = f'Reply accepted by Microsoft 365 for delivery to {ticket.requester_email}.'
            messages.success(request, outcome)
        elif result.status == EmailOutboundJob.STATUS_QUEUED:
            outcome = 'Reply queued — Microsoft 365 was busy; it will retry automatically.'
            messages.warning(request, outcome)
        elif result.status == EmailOutboundJob.STATUS_UNCERTAIN:
            outcome = ('Reply submitted but the result is unconfirmed. It will NOT be resent '
                       'automatically — check the mailbox Sent Items before resending.')
            messages.warning(request, outcome)
        else:
            outcome = f'Reply could not be sent: {result.last_error or "unknown error"}'
            messages.error(request, outcome)
        transport, status = 'graph', result.status
    else:
        outcome = f'Reply emailed to {ticket.requester_email}.'
        messages.success(request, outcome)
        transport, status = 'smtp', 'sent'

    AuditLog.log(
        user=request.user, action='update', organization=ticket.organization,
        object_type='psa.TicketComment', object_id=comment.pk,
        object_repr=f'emailed reply on {ticket.ticket_number}',
        description=f'Emailed ticket reply to requester via {transport} ({status})',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'transport': transport, 'status': status,
                    'to': ticket.requester_email},
    )


# ---------------------------------------------------------------------------
# Phase 2c — @mentions
# ---------------------------------------------------------------------------

import re as _re

# Match @username — letters, digits, underscore, dot, hyphen. Anchor on
# whitespace or start-of-string so we don't grab `email@domain.com`.
_MENTION_RE = _re.compile(r'(?:^|\s)@([A-Za-z0-9_.\-]{2,150})\b')


def _extract_mentions(body: str):
    if not body:
        return []
    # Dedupe while preserving order.
    seen = set()
    out = []
    for m in _MENTION_RE.finditer(body):
        u = m.group(1)
        if u.lower() not in seen:
            seen.add(u.lower())
            out.append(u)
    return out


def _process_mentions(ticket, comment, actor):
    """Resolve @username mentions, add each mentioned user as a watcher,
    and (best-effort) email them. Mentions only fire on staff-side
    comments — internal AND external both notify, since we treat all
    mentioned users as staff. Phase 3 portal will gate this."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    usernames = _extract_mentions(comment.body or '')
    if not usernames:
        return 0
    qs = User.objects.filter(username__in=usernames, is_active=True)
    notified = 0
    for u in qs:
        # Tenant-scope: only staff/superuser can be mentioned cross-tenant;
        # everyone else must be a member of the ticket's org.
        if not (u.is_superuser or _user_is_org_member(u, ticket.organization_id)):
            continue
        TicketWatcher.objects.get_or_create(ticket=ticket, user=u)
        if u.email and u != actor:
            _send_mention_email(ticket, comment, actor, u)
        notified += 1
    if notified:
        AuditLog.log(
            user=actor, action='create', organization=ticket.organization,
            object_type='psa.TicketComment', object_id=comment.pk,
            object_repr=f'mentions on {ticket.ticket_number}',
            description=f'Mentioned {notified} user(s) in {ticket.ticket_number}',
            extra_data={'usernames': [u.username for u in qs]},
        )
    return notified


def _user_is_org_member(user, org_id):
    if not hasattr(user, 'memberships'):
        return False
    return user.memberships.filter(organization_id=org_id, is_active=True).exists()


def _can_assign(request, org):
    """
    True if `request.user` is allowed to assign work in `org`.

    Admin = any of:
      * Django superuser
      * Django staff
      * Membership with role in {'admin', 'owner'} for `org`
      * Membership whose RoleTemplate grants `org_manage_members`
    `org=None` means MSP-wide context (staff/superuser only).
    """
    u = request.user
    if not u.is_authenticated:
        return False
    if u.is_superuser or u.is_staff or getattr(request, 'is_staff_user', False):
        return True
    if org is None:
        return False
    from accounts.models import Membership, Role
    org_id = getattr(org, 'id', None) or getattr(org, 'pk', None) or org
    qs = Membership.objects.filter(
        user=u, organization_id=org_id, is_active=True,
    ).select_related('role_template')
    for m in qs:
        if m.role in (Role.ADMIN, Role.OWNER):
            return True
        # Granular RBAC permission grants admin-equivalent assignment power.
        if m.role_template and getattr(m.role_template, 'org_manage_members', False):
            return True
    return False


def _eligible_assignees(org):
    """
    Users who can be assigned work in `org`:
      * any user with active Membership in this org
      * plus all staff / superusers (they can be assigned anywhere)
    Returns a queryset ordered by username.
    `org=None` returns staff/superusers only.
    """
    from django.contrib.auth.models import User
    org_id = getattr(org, 'id', None) or getattr(org, 'pk', None) or org if org else None
    q = models.Q(is_staff=True) | models.Q(is_superuser=True)
    if org_id:
        q = q | models.Q(memberships__organization_id=org_id, memberships__is_active=True)
    return (
        User.objects.filter(is_active=True)
        .filter(q)
        .distinct()
        .order_by('username')
    )


def _send_mention_email(ticket, comment, actor, recipient):
    try:
        from core.models import SystemSetting
        from django.core.mail import send_mail, get_connection
    except Exception:
        return
    s = SystemSetting.get_settings()
    if not s.smtp_enabled or not s.smtp_host:
        return
    try:
        from vault.encryption import decrypt
        smtp_password = decrypt(s.smtp_password) if s.smtp_password else ''
    except Exception:
        smtp_password = s.smtp_password or ''
    try:
        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=s.smtp_host, port=s.smtp_port,
            username=s.smtp_username, password=smtp_password,
            use_tls=s.smtp_use_tls, use_ssl=s.smtp_use_ssl, timeout=15,
        )
    except Exception:
        return
    site_url = (s.site_url or '').rstrip('/')
    brand = s.custom_company_name or s.site_name or 'Client St0r'
    subject = f'[{brand}] {ticket.ticket_number}: you were mentioned'
    body = (
        f'{actor.username} mentioned you in {ticket.ticket_number} '
        f'({ticket.organization.name}):\n\n'
        f'{comment.body[:1500]}\n\n'
        f'View ticket: {site_url}/psa/t/{ticket.ticket_number}/\n'
    )
    from_email = (
        f'{s.smtp_from_name} <{s.smtp_from_email}>'
        if s.smtp_from_email else s.smtp_username
    )
    try:
        send_mail(subject=subject, message=body, from_email=from_email,
                  recipient_list=[recipient.email], connection=connection,
                  fail_silently=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase 2c — Ticket merge
# ---------------------------------------------------------------------------

@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_merge(request, ticket_number):
    """
    Merge `ticket_number` (source) INTO the `target` ticket (POST param).
    Both must be in the same organization. Operations:
      * Move all source comments + attachments to target (preserve
        ordering by created_at).
      * Add a system internal-note on the target referencing the source.
      * Mark the source as `closed` with a system comment + closure
        category 'duplicate' + duplicate_of=target.
      * Audit-log both sides.
    """
    source = _scoped_ticket_for_write(request, ticket_number)
    target_number = (request.POST.get('target') or '').strip()
    if not target_number or target_number == source.ticket_number:
        messages.error(request, 'Pick a different target ticket to merge into.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': source.ticket_number}))

    target = (
        _scoped_ticket_qs(request)
        .filter(ticket_number=target_number, organization=source.organization)
        .first()
    )
    if target is None:
        messages.error(request, 'Target ticket not found in this client.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': source.ticket_number}))
    if target.closed_at or (target.status_id and target.status.is_terminal):
        messages.error(request, 'Cannot merge into a closed ticket.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': source.ticket_number}))

    # Move comments + attachments
    moved_comments = source.comments.update(ticket=target)
    moved_attachments = source.attachments.update(ticket=target)

    # System note on target
    TicketComment.objects.create(
        ticket=target, author=request.user, is_internal=True, is_system=True,
        body=(f'[merge] {source.ticket_number} merged into {target.ticket_number} '
              f'by {request.user.username}. Moved {moved_comments} comment(s) and '
              f'{moved_attachments} attachment(s).'),
    )

    # Close the source
    closed_status = (
        TicketStatus.objects.filter(slug='closed').first()
        or TicketStatus.objects.filter(is_terminal=True).order_by('sort_order').first()
    )
    source.duplicate_of = target
    source.closure_category = 'duplicate'
    source.resolution_summary = f'Merged into {target.ticket_number}'
    source.closed_at = timezone.now()
    source.resolved_at = source.resolved_at or source.closed_at
    if closed_status:
        source.status = closed_status
    source.updated_by = request.user
    source.save(update_fields=[
        'duplicate_of', 'closure_category', 'resolution_summary',
        'closed_at', 'resolved_at', 'status', 'updated_by', 'updated_at',
    ])
    TicketComment.objects.create(
        ticket=source, author=request.user, is_internal=True, is_system=True,
        body=f'[merge] Closed as duplicate of {target.ticket_number}.',
    )

    AuditLog.log(
        user=request.user, action='update', organization=source.organization,
        object_type='psa.Ticket', object_id=source.pk,
        object_repr=source.ticket_number,
        description=f'Merged {source.ticket_number} → {target.ticket_number}',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'target': target.ticket_number,
                    'comments_moved': moved_comments,
                    'attachments_moved': moved_attachments},
    )
    messages.success(request,
        f'Merged {source.ticket_number} into {target.ticket_number} '
        f'({moved_comments} comment(s), {moved_attachments} attachment(s) moved).')
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': target.ticket_number}))


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_attach(request, ticket_number):
    """Upload a file. Enforces size, MIME allowlist, tenant-scoped storage."""
    ticket = _scoped_ticket_for_write(request, ticket_number)
    f = request.FILES.get('file')
    if not f:
        messages.error(request, 'No file selected.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    if f.size > ATTACHMENT_MAX_BYTES:
        messages.error(request, f'File too large (max {ATTACHMENT_MAX_BYTES // (1024 * 1024)} MB).')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    content_type = (f.content_type or '').lower().split(';')[0].strip()
    if content_type not in ATTACHMENT_ALLOWED_MIMES:
        messages.error(request, f'File type "{content_type or "unknown"}" not allowed.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    is_internal = (request.POST.get('is_internal') or '').lower() in ('1', 'true', 'on', 'yes')
    safe_name = (f.name or 'attachment').rsplit('/', 1)[-1].rsplit('\\', 1)[-1].replace('\x00', '')[:255]

    attachment = TicketAttachment.objects.create(
        ticket=ticket, uploaded_by=request.user, file=f,
        filename=safe_name, content_type=content_type, size_bytes=f.size,
        is_internal=is_internal,
    )
    AuditLog.log(
        user=request.user, action='create', organization=ticket.organization,
        object_type='psa.TicketAttachment', object_id=attachment.pk,
        object_repr=safe_name,
        description=f'Attached {safe_name} ({f.size} bytes) to {ticket.ticket_number}',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'is_internal': is_internal, 'mime': content_type, 'size': f.size},
    )
    messages.success(request, f'Attached {safe_name}.')
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_quick_action(request, ticket_number):
    """One-button actions: assign_me, set_status, reopen, close."""
    ticket = _scoped_ticket_for_write(request, ticket_number)
    action = request.POST.get('action') or ''
    now = timezone.now()
    audit_extra = {'action': action}
    description = ''

    if action == 'assign_me':
        prev = ticket.assigned_to_id
        ticket.assigned_to = request.user
        ticket.updated_by = request.user
        ticket.save(update_fields=['assigned_to', 'updated_by', 'updated_at'])
        TicketComment.objects.create(
            ticket=ticket, author=request.user,
            body=f'Assigned to {request.user.username}.',
            is_internal=True, is_system=True,
        )
        description = f'Assigned {ticket.ticket_number} to {request.user.username}'
        audit_extra['previous_assignee_id'] = prev

    elif action == 'set_assignee':
        # Admin-only: assign the ticket to any eligible tech (or unassign).
        if not _can_assign(request, ticket.organization):
            messages.error(request, "You don't have permission to reassign this ticket.")
            return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
        from django.contrib.auth.models import User
        prev = ticket.assigned_to
        prev_id = ticket.assigned_to_id
        target_id = (request.POST.get('assignee_id') or '').strip()
        if target_id in ('', '0', 'unassigned'):
            ticket.assigned_to = None
            new_label = 'unassigned'
        else:
            try:
                target = User.objects.get(pk=int(target_id), is_active=True)
            except (User.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid assignee.')
                return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
            # Defence-in-depth: the target must be staff/superuser OR a member
            # of the ticket's org. Prevents arbitrary user IDs from being
            # injected via the form.
            eligible_ids = set(_eligible_assignees(ticket.organization).values_list('id', flat=True))
            if target.id not in eligible_ids:
                messages.error(request, 'That user cannot be assigned to this ticket.')
                return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
            ticket.assigned_to = target
            new_label = target.username
        ticket.updated_by = request.user
        ticket.save(update_fields=['assigned_to', 'updated_by', 'updated_at'])
        TicketComment.objects.create(
            ticket=ticket, author=request.user,
            body=f'Reassigned: {prev.username if prev else "unassigned"} → {new_label}.',
            is_internal=True, is_system=True,
        )
        description = (
            f'Reassigned {ticket.ticket_number}: '
            f'{prev.username if prev else "unassigned"} → {new_label}'
        )
        audit_extra['previous_assignee_id'] = prev_id

    elif action == 'set_status':
        try:
            new_status = TicketStatus.objects.get(pk=request.POST.get('status') or '')
        except TicketStatus.DoesNotExist:
            messages.error(request, 'Invalid status.')
            return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
        prev = ticket.status.name if ticket.status_id else '—'
        ticket.status = new_status
        ticket.updated_by = request.user
        update_fields = ['status', 'updated_by', 'updated_at']
        if new_status.is_terminal and not ticket.resolved_at:
            ticket.resolved_at = now
            update_fields.append('resolved_at')
        ticket.save(update_fields=update_fields)
        TicketComment.objects.create(
            ticket=ticket, author=request.user,
            body=f'Status changed: {prev} → {new_status.name}',
            is_internal=True, is_system=True,
        )
        description = f'Status of {ticket.ticket_number}: {prev} → {new_status.name}'
        audit_extra['from'] = prev
        audit_extra['to'] = new_status.name

    elif action == 'reopen':
        target = (
            TicketStatus.objects.filter(slug='in-progress').first()
            or TicketStatus.objects.filter(is_terminal=False).order_by('sort_order').first()
        )
        if not target:
            messages.error(request, 'No non-terminal status defined to reopen into.')
            return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
        prev = ticket.status.name if ticket.status_id else '—'
        ticket.status = target
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.closure_category = ''
        ticket.updated_by = request.user
        ticket.save(update_fields=['status', 'resolved_at', 'closed_at', 'closure_category', 'updated_by', 'updated_at'])
        TicketComment.objects.create(
            ticket=ticket, author=request.user,
            body=f'Reopened. Status: {prev} → {target.name}',
            is_internal=True, is_system=True,
        )
        description = f'Reopened {ticket.ticket_number}'

    elif action == 'close':
        category = request.POST.get('closure_category') or ''
        summary = (request.POST.get('resolution_summary') or '').strip()
        if not summary:
            messages.error(request, 'A resolution summary is required to close a ticket.')
            return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
        valid_categories = {key for key, _ in Ticket.CLOSURE_CATEGORIES}
        if category not in valid_categories:
            messages.error(request, 'Pick a valid closure category.')
            return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
        closed_status = (
            TicketStatus.objects.filter(slug='closed').first()
            or TicketStatus.objects.filter(is_terminal=True).order_by('sort_order').first()
        )
        if not closed_status:
            messages.error(request, 'No terminal status defined.')
            return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
        ticket.status = closed_status
        ticket.closure_category = category
        ticket.resolution_summary = summary
        ticket.closed_at = now
        if not ticket.resolved_at:
            ticket.resolved_at = now
        ticket.updated_by = request.user
        ticket.save(update_fields=[
            'status', 'closure_category', 'resolution_summary', 'closed_at',
            'resolved_at', 'updated_by', 'updated_at',
        ])
        TicketComment.objects.create(
            ticket=ticket, author=request.user,
            body=f'Closed ({dict(Ticket.CLOSURE_CATEGORIES).get(category, category)}). Resolution: {summary}',
            is_internal=False, is_system=True,
        )
        description = f'Closed {ticket.ticket_number} ({category})'
        audit_extra['closure_category'] = category
        audit_extra['summary_length'] = len(summary)

    else:
        messages.error(request, 'Unknown action.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    AuditLog.log(
        user=request.user, action='update', organization=ticket.organization,
        object_type='psa.Ticket', object_id=ticket.pk,
        object_repr=ticket.ticket_number, description=description,
        ip_address=_client_ip(request), path=request.path, extra_data=audit_extra,
    )
    messages.success(request, description)
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


# ---------------------------------------------------------------------------
# Phase 2b — watchers + canned replies
# ---------------------------------------------------------------------------

def _notify_watchers(ticket, comment, actor):
    """
    Email each watcher (excluding the comment author) about new activity.
    Best-effort: SMTP failures are logged but don't block the request.
    Internal notes go to staff watchers only — current model has all
    watchers as authenticated staff users, so we send all of them.
    """
    try:
        from core.models import SystemSetting
        from django.core.mail import send_mail, get_connection
        from django.contrib.auth import get_user_model
    except Exception:
        return 0

    settings = SystemSetting.get_settings()
    if not settings.smtp_enabled or not settings.smtp_host:
        return 0

    watchers = TicketWatcher.objects.filter(ticket=ticket).exclude(user=actor).select_related('user')
    recipients = [w.user.email for w in watchers if w.user.email]
    if not recipients:
        return 0

    try:
        from vault.encryption import decrypt
        smtp_password = decrypt(settings.smtp_password) if settings.smtp_password else ''
    except Exception:
        smtp_password = settings.smtp_password or ''

    try:
        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=settings.smtp_host, port=settings.smtp_port,
            username=settings.smtp_username, password=smtp_password,
            use_tls=settings.smtp_use_tls, use_ssl=settings.smtp_use_ssl,
            timeout=15,
        )
    except Exception:
        return 0

    from_email = (
        f'{settings.smtp_from_name} <{settings.smtp_from_email}>'
        if settings.smtp_from_email else settings.smtp_username
    )
    site_url = (settings.site_url or '').rstrip('/')
    brand = settings.custom_company_name or settings.site_name or 'Client St0r'
    detail_url = f'{site_url}/psa/t/{ticket.ticket_number}/'
    flag = ' [INTERNAL NOTE]' if comment.is_internal else ''
    subject = f'[{brand}] {ticket.ticket_number}: {ticket.subject}{flag}'
    body = (
        f'{actor.username} added a {"internal note" if comment.is_internal else "reply"} '
        f'to {ticket.ticket_number} ({ticket.organization.name}):\n\n'
        f'{comment.body[:2000]}\n\n'
        f'View ticket: {detail_url}\n'
    )

    sent = 0
    for email in recipients:
        try:
            send_mail(subject=subject, message=body, from_email=from_email,
                      recipient_list=[email], connection=connection, fail_silently=False)
            sent += 1
        except Exception:
            continue
    return sent


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_watch_toggle(request, ticket_number):
    """Subscribe / unsubscribe the current user from ticket activity."""
    ticket = _scoped_ticket_for_write(request, ticket_number)
    existing = TicketWatcher.objects.filter(ticket=ticket, user=request.user).first()
    if existing:
        existing.delete()
        messages.success(request, 'Unwatched. You will no longer receive emails for activity on this ticket.')
        action_label = 'unwatch'
    else:
        TicketWatcher.objects.create(ticket=ticket, user=request.user)
        messages.success(request, 'Watching. You will receive emails for new activity on this ticket.')
        action_label = 'watch'
    AuditLog.log(
        user=request.user, action='update',
        organization=ticket.organization,
        object_type='psa.TicketWatcher',
        object_id=ticket.pk, object_repr=ticket.ticket_number,
        description=f'{request.user.username} {action_label}ed {ticket.ticket_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


@login_required
@require_psa_enabled
def canned_reply_list(request):
    """List available canned replies. Staff/superuser see global + every
    org. Org-bound users see global + their member orgs only."""
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        qs = CannedReply.objects.select_related('organization')
    else:
        org_ids = list(
            request.user.memberships.filter(is_active=True).values_list('organization_id', flat=True)
        ) if hasattr(request.user, 'memberships') else []
        qs = CannedReply.objects.select_related('organization').filter(
            models.Q(organization__isnull=True) | models.Q(organization_id__in=org_ids)
        )
    return render(request, 'psa/canned_reply_list.html', {
        'replies': qs.order_by('organization__name', 'sort_order', 'name'),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def canned_reply_create(request):
    """Create a canned reply. Org dropdown filtered by user's eligible
    clients (no external PSA, no opt-out). Empty value = global."""
    from psa.feature_flags import clients_eligible_for_native_psa
    eligible_clients = clients_eligible_for_native_psa(request.user)
    can_create_global = request.user.is_superuser or getattr(request, 'is_staff_user', False)

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        body = (request.POST.get('body') or '').strip()
        org_id = request.POST.get('organization') or ''
        if not name or not body:
            messages.error(request, 'Name and body are required.')
            return redirect(reverse('psa:canned_reply_create'))
        org = None
        if org_id:
            try:
                org = eligible_clients.get(pk=org_id)
            except Exception:
                messages.error(request, 'That client is not eligible.')
                return redirect(reverse('psa:canned_reply_create'))
        elif not can_create_global:
            messages.error(request, 'Only staff/superusers can create global canned replies. Pick a client.')
            return redirect(reverse('psa:canned_reply_create'))
        reply = CannedReply.objects.create(
            name=name, body=body, organization=org, created_by=request.user,
            is_active=True,
        )
        AuditLog.log(
            user=request.user, action='create',
            organization=org,
            object_type='psa.CannedReply', object_id=reply.pk,
            object_repr=reply.name,
            description=f'Created canned reply "{name}" ({"global" if not org else org.name})',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Canned reply "{name}" created.')
        return redirect(reverse('psa:canned_reply_list'))

    return render(request, 'psa/canned_reply_form.html', {
        'reply': None,
        'eligible_clients': eligible_clients,
        'can_create_global': can_create_global,
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def canned_reply_edit(request, pk):
    from psa.feature_flags import clients_eligible_for_native_psa
    reply = get_object_or_404(CannedReply, pk=pk)
    # Visibility check: org-bound users can edit only their org or global
    # replies they created.
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        if reply.organization_id is None and reply.created_by_id != request.user.id:
            raise Http404()
        if reply.organization_id is not None:
            if not request.user.memberships.filter(
                organization_id=reply.organization_id, is_active=True
            ).exists():
                raise Http404()

    eligible_clients = clients_eligible_for_native_psa(request.user)
    can_create_global = request.user.is_superuser or getattr(request, 'is_staff_user', False)

    if request.method == 'POST':
        if request.POST.get('delete') == '1':
            org = reply.organization
            name = reply.name
            pk_ = reply.pk
            reply.delete()
            AuditLog.log(
                user=request.user, action='delete',
                organization=org,
                object_type='psa.CannedReply', object_id=pk_,
                object_repr=name,
                description=f'Deleted canned reply "{name}"',
                ip_address=_client_ip(request), path=request.path,
            )
            messages.success(request, f'Deleted "{name}".')
            return redirect(reverse('psa:canned_reply_list'))

        reply.name = (request.POST.get('name') or '').strip() or reply.name
        reply.body = (request.POST.get('body') or '').strip() or reply.body
        reply.is_active = request.POST.get('is_active') == 'on'
        org_id = request.POST.get('organization') or ''
        if org_id:
            try:
                reply.organization = eligible_clients.get(pk=org_id)
            except Exception:
                messages.error(request, 'That client is not eligible.')
                return redirect(reverse('psa:canned_reply_edit', kwargs={'pk': reply.pk}))
        elif can_create_global:
            reply.organization = None
        reply.save()
        AuditLog.log(
            user=request.user, action='update',
            organization=reply.organization,
            object_type='psa.CannedReply', object_id=reply.pk,
            object_repr=reply.name,
            description=f'Updated canned reply "{reply.name}"',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, 'Saved.')
        return redirect(reverse('psa:canned_reply_list'))

    return render(request, 'psa/canned_reply_form.html', {
        'reply': reply,
        'eligible_clients': eligible_clients,
        'can_create_global': can_create_global,
    })


# ---------------------------------------------------------------------------
# Phase 2c — time tracking endpoints + service catalog
# ---------------------------------------------------------------------------

@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def timer_start(request, ticket_number):
    """Start a running timer for the current user on this ticket. Idempotent
    — if a running timer already exists, it's returned unchanged."""
    ticket = _scoped_ticket_for_write(request, ticket_number)
    existing = TicketTimeEntry.objects.filter(
        ticket=ticket, user=request.user, ended_at__isnull=True,
    ).first()
    if existing:
        messages.info(request, 'Timer already running.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
    is_billable = (request.POST.get('is_billable') or '').lower() in ('1', 'true', 'on', 'yes')
    entry = TicketTimeEntry.objects.create(
        ticket=ticket, user=request.user,
        started_at=timezone.now(), is_billable=is_billable,
    )
    AuditLog.log(
        user=request.user, action='create', organization=ticket.organization,
        object_type='psa.TicketTimeEntry', object_id=entry.pk,
        object_repr=f'timer started on {ticket.ticket_number}',
        description=f'Started timer on {ticket.ticket_number} (billable={is_billable})',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, 'Timer started.')
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def timer_stop(request, ticket_number):
    """Stop the user's running timer on this ticket and finalise duration."""
    ticket = _scoped_ticket_for_write(request, ticket_number)
    entry = TicketTimeEntry.objects.filter(
        ticket=ticket, user=request.user, ended_at__isnull=True,
    ).first()
    if entry is None:
        messages.info(request, 'No running timer to stop.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
    entry.ended_at = timezone.now()
    entry.notes = (request.POST.get('notes') or entry.notes or '').strip()[:2000]
    entry.save()  # save() computes duration_minutes
    AuditLog.log(
        user=request.user, action='update', organization=ticket.organization,
        object_type='psa.TicketTimeEntry', object_id=entry.pk,
        object_repr=f'timer stopped on {ticket.ticket_number}',
        description=f'Stopped timer on {ticket.ticket_number} ({entry.duration_minutes}m, billable={entry.is_billable})',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'minutes': entry.duration_minutes, 'billable': entry.is_billable},
    )
    messages.success(request, f'Timer stopped — {entry.duration_minutes}m logged.')
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def time_entry_manual(request, ticket_number):
    """Add a manual time entry (e.g. for offline work). POST: minutes, is_billable, notes."""
    ticket = _scoped_ticket_for_write(request, ticket_number)
    try:
        minutes = int(request.POST.get('minutes') or 0)
    except ValueError:
        minutes = 0
    if minutes <= 0 or minutes > 24 * 60:
        messages.error(request, 'Minutes must be between 1 and 1440.')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
    is_billable = (request.POST.get('is_billable') or '').lower() in ('1', 'true', 'on', 'yes')
    notes = (request.POST.get('notes') or '').strip()[:2000]
    now = timezone.now()
    entry = TicketTimeEntry.objects.create(
        ticket=ticket, user=request.user,
        started_at=now - timezone.timedelta(minutes=minutes),
        ended_at=now, duration_minutes=minutes,
        is_billable=is_billable, notes=notes,
    )
    AuditLog.log(
        user=request.user, action='create', organization=ticket.organization,
        object_type='psa.TicketTimeEntry', object_id=entry.pk,
        object_repr=f'manual time entry on {ticket.ticket_number}',
        description=f'Logged {minutes}m on {ticket.ticket_number} (billable={is_billable})',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'minutes': minutes, 'billable': is_billable},
    )
    messages.success(request, f'Logged {minutes}m.')
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


# Service catalog ---------------------------------------------------------

@login_required
@require_psa_enabled
def service_catalog(request):
    """Browse-the-catalog grid. Click a tile → /psa/new/?from_catalog=<slug>."""
    is_admin = request.user.is_superuser or getattr(request, 'is_staff_user', False)
    qs = ServiceCatalogItem.objects.select_related(
        'default_priority', 'default_queue', 'default_type',
    ).order_by('sort_order', 'name')
    if not is_admin:
        qs = qs.filter(is_active=True)
    view_mode = request.GET.get('view', 'tile')
    if view_mode not in ('tile', 'list'):
        view_mode = 'tile'
    return render(request, 'psa/service_catalog.html', {
        'items': qs,
        'is_catalog_admin': is_admin,
        'view_mode': view_mode,
    })


def _catalog_admin_or_404(request):
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        raise Http404()


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def service_catalog_form(request, pk=None):
    """Create or edit a ServiceCatalogItem. Staff/superuser only.

    Phase 6.3 governance: when editing an item flagged
    `requires_approval=True`, route the editor through the propose-change
    form unless they also have `catalog_approve_change` (in which case
    they can publish straight away).
    """
    _catalog_admin_or_404(request)
    item = get_object_or_404(ServiceCatalogItem, pk=pk) if pk else None

    if item is not None and item.requires_approval:
        from accounts.permission_utils import user_has_perm
        if not user_has_perm(request.user, 'catalog_approve_change'):
            return redirect('psa:catalog_propose_change', pk=item.pk)

    queues = Queue.objects.filter(is_active=True).order_by('name')
    priorities = TicketPriority.objects.all().order_by('sort_order', 'code')
    types = TicketType.objects.filter(is_active=True).order_by('name')

    if request.method == 'POST':
        if request.POST.get('delete') == '1' and item is not None:
            name = item.name
            pk_ = item.pk
            item.delete()
            AuditLog.log(
                user=request.user, action='delete',
                object_type='psa.ServiceCatalogItem', object_id=pk_,
                object_repr=name,
                description=f'Deleted service catalog item "{name}"',
                ip_address=_client_ip(request), path=request.path,
            )
            messages.success(request, f'Deleted "{name}".')
            return redirect('psa:service_catalog')

        from django.utils.text import slugify
        import json as _json

        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        subject_tpl = (request.POST.get('default_subject') or '').strip()
        body_tpl = (request.POST.get('default_body') or '').strip()
        icon = (request.POST.get('icon') or '').strip()[:80]
        is_active = request.POST.get('is_active') == 'on'
        sort_order = int(request.POST.get('sort_order') or 0)
        fields_raw = (request.POST.get('fields_json') or '[]').strip()

        if not name:
            messages.error(request, 'Name is required.')
            return redirect(request.path)
        try:
            fields = _json.loads(fields_raw) if fields_raw else []
        except Exception as e:
            messages.error(request, f'Fields JSON is not valid: {e}')
            return redirect(request.path)
        if not isinstance(fields, list) or any(
            not isinstance(f, dict) or 'key' not in f or 'label' not in f for f in fields
        ):
            messages.error(request, 'Fields JSON must be a list of objects with at least "key" and "label".')
            return redirect(request.path)
        for f in fields:
            allowed_types = {'text', 'email', 'date', 'number', 'textarea', 'select', 'checkbox'}
            if f.get('type', 'text') not in allowed_types:
                messages.error(request, f'Invalid field type: {f.get("type")!r}. Allowed: {sorted(allowed_types)}')
                return redirect(request.path)

        try:
            queue = queues.filter(pk=request.POST.get('default_queue') or 0).first()
            priority = priorities.filter(pk=request.POST.get('default_priority') or 0).first()
            ttype = types.filter(pk=request.POST.get('default_type') or 0).first()
        except Exception:
            queue = priority = ttype = None

        if item is None:
            slug = slugify(name)
            # ensure unique
            base = slug
            n = 1
            while ServiceCatalogItem.objects.filter(slug=slug).exists():
                n += 1
                slug = f'{base}-{n}'
            item = ServiceCatalogItem(slug=slug)
        item.name = name
        item.description = description
        item.default_subject = subject_tpl
        item.default_body = body_tpl
        item.icon = icon
        item.is_active = is_active
        item.sort_order = sort_order
        item.fields_json = fields
        item.default_queue = queue
        item.default_priority = priority
        item.default_type = ttype
        # Governance toggle (Phase 6.3 — v3.17.165)
        item.requires_approval = request.POST.get('requires_approval') == 'on'
        # Direct save by an admin counts as a publish.
        item.last_published_at = timezone.now()
        item.last_published_by = request.user
        item.save()

        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            object_type='psa.ServiceCatalogItem', object_id=item.pk,
            object_repr=item.name,
            description=f'{"Updated" if pk else "Created"} service catalog item "{item.name}"',
            ip_address=_client_ip(request), path=request.path,
            extra_data={'field_count': len(fields)},
        )
        messages.success(request, f'Saved "{item.name}".')
        return redirect('psa:service_catalog')

    import json as _json
    return render(request, 'psa/service_catalog_form.html', {
        'item': item,
        'queues': queues,
        'priorities': priorities,
        'types': types,
        'fields_json_pretty': _json.dumps(item.fields_json if item else [], indent=2),
    })


# ---------------------------------------------------------------------------
# Phase 3 — Projects, Recurring Tickets, KB linking, Approvals
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
def project_list(request):
    """Tenant-scoped list of PSA projects with status filter."""
    org = get_request_organization(request)
    qs = Project.objects.select_related('client_org', 'owner')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    status = request.GET.get('status')
    if status in {'planning', 'active', 'on_hold', 'completed', 'cancelled'}:
        qs = qs.filter(status=status)
    return render(request, 'psa/project_list.html', {
        'projects': qs.order_by('-created_at')[:200],
        'status_filter': status or '',
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def project_form(request, pk=None):
    from core.models import Organization
    if pk:
        item = get_object_or_404(Project, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    def _render(selected_org_id=None):
        # v3.17.129 — admin-only Owner picker. Show eligible techs for
        # whichever org is currently picked (falls back to current org or
        # the project's saved org).
        scope_org_id = (selected_org_id if selected_org_id is not None
                        else (item.organization_id if item else (org.pk if org else None)))
        scope_org = None
        if scope_org_id:
            scope_org = Organization.objects.filter(pk=scope_org_id).first()
        can_assign = _can_assign(request, scope_org) if scope_org else (
            request.user.is_superuser or getattr(request, 'is_staff_user', False)
        )
        eligible_assignees = _eligible_assignees(scope_org) if can_assign else []
        return render(request, 'psa/project_form.html', {
            'item': item,
            'client_orgs': client_orgs,
            'status_choices': Project.STATUS_CHOICES,
            'selected_client_org_id': scope_org_id,
            'can_assign': can_assign,
            'eligible_assignees': eligible_assignees,
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('client_org_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid client.')
                return _render()
        else:
            item_org = org

        if item_org is None:
            messages.error(request, 'Please choose a client for this project.')
            return _render()

        name = (request.POST.get('name') or '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return _render(selected_org_id=item_org.pk)
        if item is None:
            item = Project(organization=item_org, name=name)
        else:
            item.organization = item_org
            item.name = name
        item.description = (request.POST.get('description') or '').strip()
        item.status = request.POST.get('status') or 'planning'
        item.start_date = request.POST.get('start_date') or None
        item.due_date = request.POST.get('due_date') or None
        item.is_billable = request.POST.get('is_billable') == 'on'
        try:
            item.estimated_hours = request.POST.get('estimated_hours') or None
        except (TypeError, ValueError):
            item.estimated_hours = None
        # Phase 35.2 (v3.17.549) — budget. Blank clears the budget; 0 is a
        # real (if unusual) budget and is kept, so `.strip()` decides rather
        # than falsiness.
        for field in ('budget_hours', 'budget_amount'):
            raw = (request.POST.get(field) or '').strip()
            try:
                setattr(item, field, raw if raw else None)
            except (TypeError, ValueError):
                setattr(item, field, None)
        # Phase 35.6 (v3.17.555) — billing type and fixed fee.
        billing_type = request.POST.get('billing_type')
        if billing_type in dict(Project.BILLING_TYPES):
            item.billing_type = billing_type
        fee_raw = (request.POST.get('fixed_fee_amount') or '').strip()
        try:
            item.fixed_fee_amount = fee_raw if fee_raw else None
        except (TypeError, ValueError):
            item.fixed_fee_amount = None
        warn_raw = (request.POST.get('budget_warn_at_percent') or '').strip()
        try:
            item.budget_warn_at_percent = max(1, min(int(warn_raw), 100)) if warn_raw else 80
        except (TypeError, ValueError):
            item.budget_warn_at_percent = 80
        client_org_id = request.POST.get('client_org') or ''
        if client_org_id:
            item.client_org = Organization.objects.filter(pk=client_org_id).first()
        else:
            item.client_org = None
        # v3.17.129 — admins can choose an owner; otherwise default to creator.
        owner_id = (request.POST.get('owner_id') or '').strip()
        if owner_id and _can_assign(request, item_org):
            from django.contrib.auth.models import User
            try:
                cand = User.objects.get(pk=int(owner_id), is_active=True)
                eligible_ids = set(_eligible_assignees(item_org).values_list('id', flat=True))
                if cand.id in eligible_ids:
                    item.owner = cand
            except (User.DoesNotExist, ValueError, TypeError):
                pass
        if not item.owner_id:
            item.owner = request.user
        item.save()

        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=item_org,
            object_type='psa.Project', object_id=item.pk,
            object_repr=item.name,
            description=f'{"Updated" if pk else "Created"} PSA project "{item.name}"',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Saved "{item.name}".')
        return redirect('psa:project_detail', pk=item.pk)

    return _render()


@login_required
@require_psa_enabled
def project_detail(request, pk):
    org = get_request_organization(request)
    qs = Project.objects.select_related('client_org', 'owner')
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    tickets = item.tickets.select_related('status', 'priority').order_by('-created_at')[:100]
    tasks = item.tasks.select_related('assigned_to').order_by('sort_order', 'created_at')
    from .models import ProjectTask
    # v3.17.129 — surface assignee picker on tasks for admins of the
    # project's org.
    can_assign = _can_assign(request, item.organization)
    eligible_assignees = _eligible_assignees(item.organization) if can_assign else []
    # Phase 35.1 (v3.17.548) — templates available to apply to this project.
    from .models import ProjectTemplate
    templates = ProjectTemplate.objects.filter(
        organization=item.organization, is_active=True).order_by('name')
    return render(request, 'psa/project_detail.html', {
        'item': item,
        'tickets': tickets,
        'tasks': tasks,
        'task_status_choices': ProjectTask.STATUS_CHOICES,
        'can_assign': can_assign,
        'eligible_assignees': eligible_assignees,
        'project_templates': templates,
        # Phase 35.2 (v3.17.549) — budget vs actuals.
        'budget': item.budget_summary(),
        # Phase 35.3 (v3.17.553) — revenue, cost and margin.
        'profit': item.profitability(),
        # Phase 35.6 (v3.17.555) — what is waiting to be billed.
        'billable': item.billable_summary(),
        'billing_types': Project.BILLING_TYPES,
    })


@login_required
@require_psa_enabled
def recurring_list(request):
    """Tenant-scoped list of recurring ticket schedules."""
    org = get_request_organization(request)
    qs = RecurringTicketSchedule.objects.select_related('queue', 'priority', 'ticket_type', 'assigned_to')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    return render(request, 'psa/recurring_list.html', {
        'schedules': qs.order_by('next_run_at')[:200],
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def recurring_form(request, pk=None):
    from core.models import Organization
    if pk:
        item = get_object_or_404(RecurringTicketSchedule, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    queues = Queue.objects.filter(is_active=True)
    priorities = TicketPriority.objects.all()
    types = TicketType.objects.all()
    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    def _render(selected_org_id=None):
        # v3.17.129 — admins can pre-pick a default assignee for the schedule.
        scope_org_id = (selected_org_id if selected_org_id is not None
                        else (item.organization_id if item else (org.pk if org else None)))
        scope_org = None
        if scope_org_id:
            scope_org = Organization.objects.filter(pk=scope_org_id).first()
        can_assign = _can_assign(request, scope_org) if scope_org else (
            request.user.is_superuser or getattr(request, 'is_staff_user', False)
        )
        eligible_assignees = _eligible_assignees(scope_org) if can_assign else []
        return render(request, 'psa/recurring_form.html', {
            'item': item,
            'queues': queues, 'priorities': priorities, 'types': types,
            'frequency_choices': RecurringTicketSchedule.FREQUENCY_CHOICES,
            'client_orgs': client_orgs,
            'selected_client_org_id': scope_org_id,
            'can_assign': can_assign,
            'eligible_assignees': eligible_assignees,
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('client_org_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid client.')
                return _render()
        else:
            item_org = org

        if item_org is None:
            messages.error(request, 'Please choose a client for this schedule.')
            return _render()

        name = (request.POST.get('name') or '').strip()
        subject = (request.POST.get('template_subject') or '').strip()
        if not name or not subject:
            messages.error(request, 'Name and template subject are required.')
            return _render(selected_org_id=item_org.pk)
        try:
            queue = queues.get(pk=request.POST.get('queue'))
            priority = priorities.get(pk=request.POST.get('priority'))
            ticket_type = types.get(pk=request.POST.get('ticket_type'))
        except (Queue.DoesNotExist, TicketPriority.DoesNotExist,
                TicketType.DoesNotExist, ValueError):
            messages.error(request, 'Pick a valid queue / priority / type.')
            return _render(selected_org_id=item_org.pk)

        if item is None:
            item = RecurringTicketSchedule(
                organization=item_org,
                queue=queue, priority=priority, ticket_type=ticket_type,
                next_run_at=timezone.now(),
                created_by=request.user,
            )
        else:
            item.organization = item_org
            item.queue = queue
            item.priority = priority
            item.ticket_type = ticket_type
        item.name = name
        item.template_subject = subject
        item.template_body = (request.POST.get('template_body') or '').strip()
        item.frequency = request.POST.get('frequency') or 'monthly'
        try:
            item.interval = max(1, int(request.POST.get('interval') or 1))
        except ValueError:
            item.interval = 1
        item.is_active = request.POST.get('is_active') == 'on'

        first_run = request.POST.get('next_run_at')
        if first_run:
            try:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(first_run)
                if parsed:
                    item.next_run_at = parsed
            except (TypeError, ValueError):
                pass

        client_org_id = request.POST.get('client_org') or ''
        if client_org_id:
            item.client_org = Organization.objects.filter(pk=client_org_id).first()
        else:
            item.client_org = None

        # v3.17.129 — admins can set the default assignee for generated tickets.
        if 'assigned_to' in request.POST and _can_assign(request, item_org):
            from django.contrib.auth.models import User
            posted = (request.POST.get('assigned_to') or '').strip()
            if posted in ('', '0', 'unassigned'):
                item.assigned_to = None
            else:
                try:
                    cand = User.objects.get(pk=int(posted), is_active=True)
                    eligible_ids = set(
                        _eligible_assignees(item_org).values_list('id', flat=True)
                    )
                    if cand.id in eligible_ids:
                        item.assigned_to = cand
                except (User.DoesNotExist, ValueError, TypeError):
                    pass

        item.save()
        messages.success(request, f'Saved schedule "{item.name}".')
        return redirect('psa:recurring_list')

    return _render()


def _check_kb_perm(user, perm_name):
    """Cross-org KB permission check.

    Superusers / staff users always pass. For everyone else we walk all
    of their active memberships — having the permission on ANY membership
    grants it (typical for KB which is mostly cross-org / global).
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_staff', False):
        return True
    from accounts.models import Membership
    qs = Membership.objects.filter(user=user, is_active=True).select_related('role_template')
    for m in qs:
        perms = m.get_permissions()
        if getattr(perms, perm_name, False):
            return True
    return False


def _flatten_categories(cats_by_parent, parent_id=None, depth=0):
    """Walk a parent_id→children dict, yielding (cat, depth) in tree order."""
    for c in cats_by_parent.get(parent_id, []):
        yield c, depth
        yield from _flatten_categories(cats_by_parent, c.id, depth + 1)


@login_required
@require_psa_enabled
def kb_browse(request):
    """KB browser — wraps docs.Document filtered to global KB articles.
    Shows a category tree sidebar; ?category=<slug> filters to that
    category and all its descendants.
    """
    from docs.models import Document, DocumentCategory

    # Global categories tree (parent first, then children)
    cats_qs = DocumentCategory.objects.filter(
        organization__isnull=True
    ).order_by('order', 'name')
    cats = list(cats_qs)
    # Build a parent_id → [children] map for cheap recursive rendering
    cats_by_parent = {}
    for c in cats:
        cats_by_parent.setdefault(c.parent_id, []).append(c)
    roots = cats_by_parent.get(None, [])

    # Resolve ?category=<slug> selection
    cat_slug = (request.GET.get('category') or '').strip()
    selected_cat = None
    selected_breadcrumb = []
    descendant_ids = []
    if cat_slug:
        selected_cat = next((c for c in cats if c.slug == cat_slug), None)
        if selected_cat:
            # Walk up the tree to build breadcrumbs
            walk = selected_cat
            while walk:
                selected_breadcrumb.insert(0, walk)
                walk = walk.parent if walk.parent_id else None
            # Walk down to gather all descendant IDs (inclusive)
            stack = [selected_cat.id]
            descendant_ids = [selected_cat.id]
            while stack:
                pid = stack.pop()
                for child in cats_by_parent.get(pid, []):
                    descendant_ids.append(child.id)
                    stack.append(child.id)

    # Articles
    qs = Document.objects.filter(is_global=True, is_archived=False)
    if descendant_ids:
        qs = qs.filter(category_id__in=descendant_ids)

    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(models.Q(title__icontains=q) | models.Q(body__icontains=q))

    articles = qs.select_related('category', 'created_by').order_by('-updated_at')[:100]

    # Permission flags — drive button visibility in the template.
    can_edit_kb = _check_kb_perm(request.user, 'kb_edit_articles')
    can_move_kb = _check_kb_perm(request.user, 'kb_move_articles')
    can_manage_categories = _check_kb_perm(request.user, 'kb_manage_categories')

    # Pre-built flat category list for the "Move to →" dropdown.
    flat_cats = list(_flatten_categories(cats_by_parent))

    return render(request, 'psa/kb_browse.html', {
        'articles': articles,
        'query': q,
        'category_roots': roots,
        'cats_by_parent': cats_by_parent,
        'selected_cat': selected_cat,
        'selected_breadcrumb': selected_breadcrumb,
        'all_categories_count': cats_qs.count(),
        'can_edit_kb': can_edit_kb,
        'can_move_kb': can_move_kb,
        'can_manage_categories': can_manage_categories,
        'flat_categories': flat_cats,
    })


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def kb_move_articles(request):
    """Bulk-move KB articles between categories.

    POST body:
      article_ids[] -- list of Document IDs (must be is_global=True)
      target_category_id -- DocumentCategory.id, or empty/'' for "uncategorized"

    Permission: kb_move_articles (cross-org check via _check_kb_perm).
    """
    from django.core.exceptions import PermissionDenied
    from docs.models import Document, DocumentCategory

    if not _check_kb_perm(request.user, 'kb_move_articles'):
        raise PermissionDenied("You don't have permission to move KB articles.")

    raw_ids = request.POST.getlist('article_ids') or request.POST.getlist('article_ids[]')
    try:
        article_ids = [int(x) for x in raw_ids if str(x).strip()]
    except (TypeError, ValueError):
        article_ids = []

    if not article_ids:
        messages.error(request, 'Select at least one article to move.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('psa:kb_browse'))

    target_raw = (request.POST.get('target_category_id') or '').strip()
    target_id = None
    target_cat = None
    if target_raw:
        try:
            target_id = int(target_raw)
        except (TypeError, ValueError):
            target_id = None
        if target_id is not None:
            target_cat = DocumentCategory.objects.filter(
                pk=target_id, organization__isnull=True
            ).first()
            if not target_cat:
                messages.error(request, 'Invalid target category.')
                return redirect(request.META.get('HTTP_REFERER') or reverse('psa:kb_browse'))

    # Single-query update across all selected global KB articles.
    qs = Document.objects.filter(pk__in=article_ids, is_global=True)
    n = qs.update(category=target_cat)

    AuditLog.log(
        user=request.user,
        action='update',
        organization=None,
        object_type='docs.Document',
        object_id=None,
        object_repr=f'KB bulk move ({n} article{"s" if n != 1 else ""})',
        description=(
            f'Moved {n} KB article(s) to '
            f'{target_cat.name if target_cat else "Uncategorized"} '
            f'(ids={article_ids})'
        ),
        ip_address=_client_ip(request),
        path=request.path,
    )

    if n:
        target_label = target_cat.name if target_cat else 'Uncategorized'
        messages.success(
            request,
            f'Moved {n} article{"s" if n != 1 else ""} to "{target_label}".'
        )
    else:
        messages.warning(request, 'No matching KB articles to move.')

    # Preserve the user's current category filter on redirect.
    next_url = request.POST.get('next') or reverse('psa:kb_browse')
    return redirect(next_url)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_kb_link(request, ticket_number):
    """Link a docs.Document KB article to a ticket."""
    from docs.models import Document
    org = get_request_organization(request)
    qs = Ticket.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)

    article_id = request.POST.get('article_id')
    if not article_id:
        messages.error(request, 'Pick an article.')
        return redirect('psa:ticket_detail', ticket_number=ticket_number)

    article = get_object_or_404(Document, pk=article_id, is_global=True)
    link, created = TicketKBLink.objects.get_or_create(
        ticket=ticket, article=article,
        defaults={'linked_by': request.user, 'note': request.POST.get('note', '')[:300]},
    )
    if created:
        messages.success(request, f'Linked KB: {article.title}')
        AuditLog.log(
            user=request.user, action='update',
            organization=ticket.organization,
            object_type='psa.Ticket', object_id=ticket.pk,
            object_repr=ticket.ticket_number,
            description=f'Linked KB article "{article.title}" to {ticket.ticket_number}',
            ip_address=_client_ip(request), path=request.path,
        )
    else:
        messages.info(request, f'Already linked to "{article.title}".')
    return redirect('psa:ticket_detail', ticket_number=ticket_number)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_kb_unlink(request, ticket_number, link_pk):
    org = get_request_organization(request)
    qs = TicketKBLink.objects.select_related('ticket', 'article')
    if org is not None:
        qs = qs.filter(ticket__organization=org)
    link = get_object_or_404(qs, pk=link_pk, ticket__ticket_number=ticket_number)
    title = link.article.title
    link.delete()
    messages.success(request, f'Unlinked "{title}".')
    return redirect('psa:ticket_detail', ticket_number=ticket_number)


@login_required
@require_psa_enabled
def approval_list(request):
    """Tenant-scoped list of PSA approvals (pending first)."""
    org = get_request_organization(request)
    qs = PSAApproval.objects.select_related('requested_by', 'decided_by', 'related_ticket')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    status = request.GET.get('status', 'pending')
    if status in {'pending', 'approved', 'denied', 'cancelled'}:
        qs = qs.filter(status=status)
    return render(request, 'psa/approval_list.html', {
        'approvals': qs.order_by('-requested_at')[:200],
        'status_filter': status,
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def approval_decide(request, pk):
    org = get_request_organization(request)
    qs = PSAApproval.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    approval = get_object_or_404(qs, pk=pk)
    if approval.status != 'pending':
        messages.error(request, 'This approval has already been decided.')
        return redirect('psa:approval_list')

    decision = request.POST.get('decision')
    comment = (request.POST.get('comment') or '').strip()
    if decision not in {'approve', 'deny'}:
        messages.error(request, 'Pick approve or deny.')
        return redirect('psa:approval_list')

    approval.decide(user=request.user, approved=(decision == 'approve'), comment=comment)
    # Phase 20 v6 (v3.17.274): the model's decide() now writes the
    # AuditLog row; the view just redirects.
    messages.success(request, f'{decision.title()}d.')
    return redirect('psa:approval_list')


@login_required
@require_psa_enabled
def approval_history(request, pk):
    """Phase 20 v6 (v3.17.274): per-approval audit trail viewer."""
    org = get_request_organization(request)
    qs = PSAApproval.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    approval = get_object_or_404(qs, pk=pk)
    return render(request, 'psa/approval_history.html', {
        'approval': approval,
        'history': approval.history(),
    })


# ---------------------------------------------------------------------------
# Phase 4 — Contracts + Email Ingestion
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
def contract_list(request):
    """Tenant-scoped contract list."""
    org = get_request_organization(request)
    qs = Contract.objects.select_related('client_org')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    return render(request, 'psa/contract_list.html', {
        'contracts': qs.order_by('-start_date')[:200],
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def contract_form(request, pk=None):
    from core.models import Organization
    if pk:
        item = get_object_or_404(Contract, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    def _render(selected_org_id=None):
        return render(request, 'psa/contract_form.html', {
            'item': item,
            'client_orgs': client_orgs,
            'contract_types': Contract.CONTRACT_TYPES,
            'status_choices': Contract.STATUS_CHOICES,
            'priorities': TicketPriority.objects.all().order_by('sort_order'),
            'selected_client_org_id': selected_org_id if selected_org_id is not None
                                       else (item.organization_id if item else (org.pk if org else None)),
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('client_org_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid client.')
                return _render()
        else:
            item_org = org

        if item_org is None:
            messages.error(request, 'Please choose a client for this contract.')
            return _render()

        name = (request.POST.get('name') or '').strip()
        client_org_id = request.POST.get('client_org')
        if not name or not client_org_id:
            messages.error(request, 'Name and client are required.')
            return _render(selected_org_id=item_org.pk)
        try:
            client_org = Organization.objects.get(pk=client_org_id)
        except Organization.DoesNotExist:
            messages.error(request, 'Client not found.')
            return _render(selected_org_id=item_org.pk)

        if item is None:
            item = Contract(organization=item_org, client_org=client_org, name=name,
                            created_by=request.user, start_date=timezone.now().date())
        else:
            item.organization = item_org
            item.client_org = client_org
            item.name = name
        item.contract_type = request.POST.get('contract_type') or 'block_hours'
        item.status = request.POST.get('status') or 'draft'
        item.start_date = request.POST.get('start_date') or item.start_date
        item.end_date = request.POST.get('end_date') or None
        try:
            item.total_hours = request.POST.get('total_hours') or 0
        except (TypeError, ValueError):
            item.total_hours = 0
        try:
            item.hourly_rate = request.POST.get('hourly_rate') or 0
            item.overage_rate = request.POST.get('overage_rate') or 0
        except (TypeError, ValueError):
            pass
        item.notes = (request.POST.get('notes') or '').strip()

        # Phase 1 contract-engine fields (rollover, auto-renew, role gates).
        # rolled_over_minutes / rollover_expires_at / parent_contract are
        # intentionally NOT exposed here — they're set by the renewal cron.
        from decimal import Decimal, InvalidOperation

        def _decimal(name, default='0'):
            try:
                return Decimal(request.POST.get(name) or default)
            except (InvalidOperation, TypeError):
                return Decimal(default)

        def _int(name, default=0):
            try:
                return int(request.POST.get(name) or default)
            except (TypeError, ValueError):
                return default

        def _bool(name):
            return (request.POST.get(name) or '').lower() in ('1', 'true', 'on', 'yes')

        def _csv_list(name):
            raw = (request.POST.get(name) or '').strip()
            if not raw:
                return []
            return [s.strip() for s in raw.split(',') if s.strip()]

        item.rollover_percent = _decimal('rollover_percent')
        item.rollover_expiry_days = _int('rollover_expiry_days')
        item.auto_renew = _bool('auto_renew')
        item.auto_renew_period_months = _int('auto_renew_period_months', 12) or 12
        item.proration_enabled = _bool('proration_enabled')
        item.billable_role_codes = _csv_list('billable_role_codes')
        item.excluded_role_codes = _csv_list('excluded_role_codes')

        # SLA matrix — POST keys are sla_<code>_response and sla_<code>_resolution.
        # Empty string = "use priority default" (omit from matrix).
        matrix = {}
        for p in TicketPriority.objects.all():
            r_raw = request.POST.get(f'sla_{p.code}_response') or ''
            x_raw = request.POST.get(f'sla_{p.code}_resolution') or ''
            entry = {}
            if r_raw.strip():
                try:
                    entry['response_minutes'] = max(0, int(r_raw))
                except ValueError:
                    pass
            if x_raw.strip():
                try:
                    entry['resolution_minutes'] = max(0, int(x_raw))
                except ValueError:
                    pass
            if entry:
                matrix[p.code] = entry
        item.sla_matrix = matrix
        item.save()

        # Bundle items — JSON payload from the dynamic editor on the form.
        # Reconcile by pk: update existing rows, create new ones, delete
        # those no longer in the submitted list.
        import json
        bundle_json = request.POST.get('bundle_items_json') or '[]'
        try:
            bundle_rows = json.loads(bundle_json)
        except (ValueError, TypeError):
            bundle_rows = []

        if isinstance(bundle_rows, list):
            from psa.models import ContractBundleItem
            from decimal import Decimal, InvalidOperation

            seen_pks = set()
            for i, row in enumerate(bundle_rows):
                if not isinstance(row, dict):
                    continue
                row_name = (row.get('name') or '').strip()
                if not row_name:
                    continue
                try:
                    qty = Decimal(str(row.get('quantity') or '1'))
                    price = Decimal(str(row.get('unit_price') or '0'))
                except InvalidOperation:
                    qty, price = Decimal('1'), Decimal('0')
                period = row.get('recurring_period') or 'monthly'
                if period not in ('one_time', 'monthly', 'quarterly', 'yearly'):
                    period = 'monthly'

                row_pk = row.get('pk') or ''
                existing = None
                if row_pk:
                    try:
                        existing = ContractBundleItem.objects.filter(
                            pk=int(row_pk), contract=item
                        ).first()
                    except (ValueError, TypeError):
                        existing = None
                if existing:
                    existing.name = row_name[:200]
                    existing.quantity = qty
                    existing.unit_label = (row.get('unit_label') or '')[:40]
                    existing.unit_price = price
                    existing.recurring_period = period
                    existing.sort_order = i
                    existing.save()
                    seen_pks.add(existing.pk)
                else:
                    new_b = ContractBundleItem.objects.create(
                        contract=item,
                        name=row_name[:200],
                        quantity=qty,
                        unit_label=(row.get('unit_label') or '')[:40],
                        unit_price=price,
                        recurring_period=period,
                        sort_order=i,
                    )
                    seen_pks.add(new_b.pk)

            # Delete rows the user removed (pks in DB but not in submitted JSON)
            item.bundle_items.exclude(pk__in=seen_pks).delete()

        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=item_org,
            object_type='psa.Contract', object_id=item.pk,
            object_repr=str(item),
            description=f'{"Updated" if pk else "Created"} contract "{item.name}"',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Saved "{item.name}".')
        return redirect('psa:contract_detail', pk=item.pk)

    return _render()


@login_required
@require_psa_enabled
def contract_detail(request, pk):
    """Read-only contract detail with bundle items + profitability snapshot.

    v3.17.130 — Phase 1.2 of the contract engine.
    """
    org = get_request_organization(request)
    qs = Contract.objects.select_related('client_org', 'organization', 'parent_contract')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    item = get_object_or_404(qs, pk=pk)

    bundle_items = item.bundle_items.all()
    snapshot = item.profitability_snapshot()

    # Pull priority list so we can render the SLA-matrix preview with
    # human labels alongside any per-priority overrides.
    priorities = list(TicketPriority.objects.all().order_by('sort_order'))

    return render(request, 'psa/contract_detail.html', {
        'item': item,
        'bundle_items': bundle_items,
        'snapshot': snapshot,
        'priorities': priorities,
        'effective_hours_remaining': item.effective_hours_remaining(),
        'renewal_history': item.renewals.all().order_by('-start_date') if hasattr(item, 'renewals') else [],
    })


@login_required
@require_psa_enabled
def email_config_list(request):
    org = get_request_organization(request)
    qs = EmailIngestionConfig.objects.select_related('default_queue', 'default_priority', 'default_type')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    return render(request, 'psa/email_config_list.html', {
        'configs': qs.order_by('name')[:100],
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def email_config_form(request, pk=None):
    from core.models import Organization
    from integrations.models import M365Connection
    if pk:
        item = get_object_or_404(EmailIngestionConfig, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    queues = Queue.objects.filter(is_active=True)
    priorities = TicketPriority.objects.all()
    types = TicketType.objects.all()
    client_orgs = Organization.objects.filter(is_active=True).order_by('name')
    # Issue #142 — M365 Graph mailbox source reuses an existing M365 connection's
    # app-registration credentials.
    m365_connections = M365Connection.objects.filter(is_active=True).select_related(
        'organization').order_by('organization__name', 'name')

    def _render(selected_org_id=None):
        return render(request, 'psa/email_config_form.html', {
            'item': item,
            'queues': queues, 'priorities': priorities, 'types': types,
            'client_orgs': client_orgs,
            'm365_connections': m365_connections,
            'selected_client_org_id': selected_org_id if selected_org_id is not None
                                       else (item.organization_id if item else (org.pk if org else None)),
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('client_org_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid client.')
                return _render()
        else:
            item_org = org

        if item_org is None:
            messages.error(request, 'Please choose a client for this email config.')
            return _render()

        source = (request.POST.get('source') or 'imap').strip()
        if source not in ('imap', 'graph'):
            source = 'imap'
        outbound_method = (request.POST.get('outbound_method') or 'smtp').strip()
        if outbound_method not in ('smtp', 'graph'):
            outbound_method = 'smtp'
        name = (request.POST.get('name') or '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return _render(selected_org_id=item_org.pk)

        # Source-specific required fields (issue #142).
        host = (request.POST.get('imap_host') or '').strip()
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        m365_conn = None
        graph_mailbox = (request.POST.get('graph_mailbox') or '').strip()
        # An M365 connection + mailbox are needed when Graph is used for EITHER
        # inbound (source) or outbound.
        needs_graph = (source == 'graph') or (outbound_method == 'graph')
        if needs_graph:
            try:
                m365_conn = M365Connection.objects.get(
                    pk=request.POST.get('m365_connection'), is_active=True)
            except (M365Connection.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Select an active Microsoft 365 connection for Graph.')
                return _render(selected_org_id=item_org.pk)
            if not graph_mailbox:
                messages.error(request, 'Enter the Microsoft 365 mailbox address (e.g. support@contoso.com).')
                return _render(selected_org_id=item_org.pk)
        if source == 'imap':
            if not host or not username:
                messages.error(request, 'Host and username are required for IMAP.')
                return _render(selected_org_id=item_org.pk)

        try:
            port = int(request.POST.get('imap_port') or 993)
        except ValueError:
            port = 993

        try:
            queue = queues.get(pk=request.POST.get('default_queue'))
            priority = priorities.get(pk=request.POST.get('default_priority'))
            ticket_type = types.get(pk=request.POST.get('default_type'))
        except (Queue.DoesNotExist, TicketPriority.DoesNotExist, TicketType.DoesNotExist, ValueError):
            messages.error(request, 'Pick valid defaults.')
            return _render(selected_org_id=item_org.pk)

        if item is None:
            item = EmailIngestionConfig(organization=item_org, default_queue=queue,
                                        default_priority=priority, default_type=ticket_type)
        else:
            item.organization = item_org
            item.default_queue = queue
            item.default_priority = priority
            item.default_type = ticket_type
        item.name = name
        item.source = source
        item.outbound_method = outbound_method
        item.smtp_fallback_enabled = request.POST.get('smtp_fallback_enabled') == 'on'
        if needs_graph:
            item.m365_connection = m365_conn
            item.graph_mailbox = graph_mailbox
        else:
            item.m365_connection = None
            item.graph_mailbox = ''
        if source == 'imap':
            item.imap_host = host
            item.imap_port = port
            item.use_ssl = request.POST.get('use_ssl') == 'on'
            item.username = username
            if password:
                item.set_password(password)
        item.folder = (request.POST.get('folder') or 'INBOX').strip()
        item.subject_ticket_pattern = (request.POST.get('subject_ticket_pattern') or 'PSA-\\d{4}-\\d{6}')[:200]
        item.is_active = request.POST.get('is_active') == 'on'
        try:
            item.poll_interval_minutes = max(1, int(request.POST.get('poll_interval_minutes') or 5))
        except ValueError:
            item.poll_interval_minutes = 5
        item.save()

        messages.success(request, f'Saved "{item.name}".')
        return redirect('psa:email_config_list')

    return _render()


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET'])
def email_graph_readiness(request, pk):
    """Issue #142 outbound — JSON readiness for the Graph transport. Reports
    separate inbound (Mail.Read) and outbound (Mail.Send) status. Never returns
    tokens, secrets, or raw auth headers — only Graph error messages."""
    from django.http import JsonResponse
    config = get_object_or_404(EmailIngestionConfig, pk=pk)
    conn = config.m365_connection
    result = {
        'connection_active': bool(conn and conn.is_active),
        'mailbox_configured': bool(config.graph_mailbox),
        'token_ok': False,
        'inbound_ok': False,
        'inbound_message': '',
        'outbound_verified': bool(config.graph_send_verified_at),
        'outbound_message': '',
    }
    if config.graph_send_verified_at:
        result['outbound_message'] = f'Verified {config.graph_send_verified_at:%Y-%m-%d %H:%M} UTC'
    elif config.graph_send_last_error:
        result['outbound_message'] = config.graph_send_last_error
    else:
        result['outbound_message'] = 'Not yet tested — use Test outbound.'

    if not result['connection_active']:
        result['inbound_message'] = 'No active Microsoft 365 connection.'
        return JsonResponse(result)
    if not result['mailbox_configured']:
        result['inbound_message'] = 'No mailbox address configured.'
        return JsonResponse(result)

    try:
        from integrations.providers.m365 import M365Provider
        creds = conn.get_credentials()
        provider = M365Provider(conn.tenant_id, creds.get('client_id', ''),
                                creds.get('client_secret', ''))
        folder = config.folder or 'inbox'
        if folder.upper() == 'INBOX':
            folder = 'inbox'
        probe = provider.probe_mailbox(config.graph_mailbox, folder)
        if probe.get('success'):
            result['token_ok'] = True
            result['inbound_ok'] = True
            result['inbound_message'] = 'Mail.Read OK'
        else:
            err = probe.get('error', '')
            # If we got an HTTP status back, the token was acquired.
            result['token_ok'] = 'HTTP' in err
            result['inbound_ok'] = False
            result['inbound_message'] = err
    except Exception as e:  # noqa: BLE001
        result['token_ok'] = False
        result['inbound_message'] = f'Token/connection error: {e}'[:300]
    return JsonResponse(result)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def email_graph_test_send(request, pk):
    """Issue #142 outbound — send a single, clearly-labeled test message to an
    admin-specified recipient to verify Mail.Send + Exchange RBAC scope."""
    from django.http import JsonResponse
    from django.utils import timezone
    import json
    config = get_object_or_404(EmailIngestionConfig, pk=pk)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        data = {}
    from psa.graph_outbound import validate_recipients, _extract_error, classify_error
    valid, _invalid = validate_recipients([(data.get('test_recipient') or '').strip()])
    if not valid:
        return JsonResponse({'success': False, 'error': 'Enter a valid test recipient address.'}, status=400)

    conn = config.m365_connection
    if not (conn and conn.is_active and config.graph_mailbox):
        return JsonResponse({'success': False,
                             'error': 'Graph outbound is not fully configured (connection/mailbox).'},
                            status=400)

    from integrations.providers.m365 import M365Provider
    from psa.email_parsing import sanitize_html
    creds = conn.get_credentials()
    provider = M365Provider(conn.tenant_id, creds.get('client_id', ''),
                            creds.get('client_secret', ''))
    message = {
        'subject': '[TEST] ClientSt0r Microsoft Graph outbound test',
        'body': {'contentType': 'HTML', 'content': sanitize_html(
            '<p>This is a <strong>test message</strong> sent by ClientSt0r to verify '
            'Microsoft Graph outbound (Mail.Send) for this mailbox. No action is required.</p>')},
        'toRecipients': [{'emailAddress': {'address': valid[0]}}],
    }
    try:
        resp = provider.send_mail(config.graph_mailbox, message, save_to_sent_items=True)
    except Exception as e:  # noqa: BLE001
        config.graph_send_last_error = str(e)[:300]
        config.save(update_fields=['graph_send_last_error'])
        return JsonResponse({'success': False, 'error': f'Send failed: {e}'[:300]}, status=502)

    if resp.status_code in (200, 202):
        config.graph_send_verified_at = timezone.now()
        config.graph_send_last_error = ''
        config.save(update_fields=['graph_send_verified_at', 'graph_send_last_error'])
        return JsonResponse({
            'success': True,
            'request_id': resp.headers.get('request-id', ''),
            'message': (f'Accepted (HTTP {resp.status_code}). Note: 202 means Microsoft accepted '
                        'the message for processing — not a final delivery confirmation.'),
        })

    msg, _req = _extract_error(resp)
    detail = msg
    if resp.status_code == 403:
        detail = (f'{msg} — Mail.Send may not be granted, or the mailbox is outside the app\'s '
                  'Exchange RBAC scope.')
    config.graph_send_last_error = f'HTTP {resp.status_code}: {detail}'[:300]
    config.save(update_fields=['graph_send_last_error'])
    return JsonResponse({'success': False, 'error': config.graph_send_last_error,
                         'category': classify_error(resp.status_code, msg)}, status=502)


# ---------------------------------------------------------------------------
# Phase 5 — Quotes + Expenses
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
def quote_list(request):
    org = get_request_organization(request)
    qs = Quote.objects.select_related('client_org', 'created_by')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    status = request.GET.get('status')
    if status in {'draft', 'sent', 'accepted', 'rejected', 'expired'}:
        qs = qs.filter(status=status)
    return render(request, 'psa/quote_list.html', {
        'quotes': qs.order_by('-created_at')[:200],
        'status_filter': status or '',
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def quote_form(request, pk=None):
    from core.models import Organization, SystemSetting
    if pk:
        item = get_object_or_404(Quote, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    def _render(selected_org_id=None):
        settings = SystemSetting.get_settings()
        default_tax_rate = settings.psa_default_tax_rate if not item else item.tax_rate
        return render(request, 'psa/quote_form.html', {
            'item': item,
            'client_orgs': client_orgs,
            'status_choices': Quote.STATUS_CHOICES,
            'line_items': item.line_items.all() if item else [],
            'default_tax_rate': default_tax_rate,
            'selected_client_org_id': selected_org_id if selected_org_id is not None
                                       else (item.organization_id if item else (org.pk if org else None)),
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('client_org_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid client.')
                return _render()
        else:
            item_org = org

        if item_org is None:
            messages.error(request, 'Please choose a client for this quote.')
            return _render()

        title = (request.POST.get('title') or '').strip()
        client_org_id = request.POST.get('client_org')
        if not title or not client_org_id:
            messages.error(request, 'Title and client are required.')
            return _render(selected_org_id=item_org.pk)
        try:
            client_org = Organization.objects.get(pk=client_org_id)
        except Organization.DoesNotExist:
            messages.error(request, 'Client not found.')
            return _render(selected_org_id=item_org.pk)

        if item is None:
            item = Quote(organization=item_org, client_org=client_org, title=title,
                         created_by=request.user)
        else:
            item.organization = item_org
            item.client_org = client_org
            item.title = title
        item.description = (request.POST.get('description') or '').strip()
        item.status = request.POST.get('status') or 'draft'
        item.valid_until = request.POST.get('valid_until') or None
        try:
            item.tax_rate = request.POST.get('tax_rate') or 0
        except (TypeError, ValueError):
            item.tax_rate = 0
        item.save()

        # Replace line items if posted
        line_descs = request.POST.getlist('li_description')
        line_qtys = request.POST.getlist('li_quantity')
        line_prices = request.POST.getlist('li_unit_price')
        if line_descs:
            item.line_items.all().delete()
            for i, (d, q, p) in enumerate(zip(line_descs, line_qtys, line_prices)):
                if not (d or '').strip():
                    continue
                try:
                    qf = float(q or 1)
                    pf = float(p or 0)
                except ValueError:
                    qf, pf = 1, 0
                QuoteLineItem.objects.create(
                    quote=item, sort_order=i,
                    description=d.strip()[:300], quantity=qf, unit_price=pf,
                )
        item.recompute_totals()

        messages.success(request, f'Saved "{item.quote_number}".')
        return redirect('psa:quote_list')

    return _render()


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def quote_accept(request, pk):
    org = get_request_organization(request)
    qs = Quote.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    # Phase 20 v7 (v3.17.275): block acceptance while approvals are open.
    if item.has_open_approvals:
        messages.error(
            request,
            f'Quote {item.quote_number} has open approvals — resolve the '
            f'chain at /psa/approvals/ before accepting.',
        )
        return redirect('psa:quote_detail', pk=item.pk)
    create = request.POST.get('create_ticket') == 'on'
    create_proj = request.POST.get('create_project') == 'on'
    queue = Queue.objects.filter(is_active=True).first()
    priority = TicketPriority.objects.first()
    ttype = TicketType.objects.first()
    status = TicketStatus.objects.filter(slug='new').first()
    try:
        item.mark_accepted(user=request.user, create_ticket=create,
                           queue=queue, priority=priority,
                           ticket_type=ttype, status=status,
                           create_project=create_proj)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('psa:quote_detail', pk=item.pk)
    AuditLog.log(
        user=request.user, action='update',
        organization=org or item.organization,
        object_type='psa.Quote', object_id=item.pk,
        object_repr=item.quote_number,
        description=(
            f'Accepted quote {item.quote_number}; '
            f'ticket={item.converted_ticket_id or "—"}; '
            f'project={item.converted_project_id or "—"}'
        ),
        ip_address=_client_ip(request), path=request.path,
    )
    if item.converted_project:
        messages.success(
            request,
            f'Accepted. Project "{item.converted_project.name}" created'
            + (f' (ticket {item.converted_ticket.ticket_number}).' if item.converted_ticket else '.'),
        )
        return redirect('psa:project_detail', pk=item.converted_project.pk)
    if item.converted_ticket:
        messages.success(request, f'Accepted. Ticket {item.converted_ticket.ticket_number} created.')
        return redirect('psa:ticket_detail', ticket_number=item.converted_ticket.ticket_number)
    messages.success(request, 'Quote accepted.')
    return redirect('psa:quote_list')


@login_required
@require_psa_enabled
def ticket_route_urls(request, ticket_number):
    """Phase 21 v11 (v3.17.317): mobile dispatch routing helper.

    Returns JSON `{address, urls: {google, apple, waze}}` so the PWA
    can render a "Navigate" picker on the ticket detail page. URLs
    use the ticket's `client_org` (else `organization`) address —
    fails gracefully when no street address is set.
    """
    from urllib.parse import quote_plus
    org = get_request_organization(request)
    qs = Ticket.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)
    target_org = ticket.organization
    addr = (target_org.full_address or '').strip() if target_org else ''
    if not addr:
        return JsonResponse({
            'success': False,
            'error': 'No street address on the ticket\'s organization.',
            'address': '', 'urls': {},
        })
    encoded = quote_plus(addr)
    return JsonResponse({
        'success': True,
        'address': addr,
        'urls': {
            # Google Maps universal URL
            'google': f'https://www.google.com/maps/dir/?api=1&destination={encoded}',
            # Apple Maps universal URL
            'apple': f'https://maps.apple.com/?daddr={encoded}',
            # Waze deep link
            'waze': f'https://www.waze.com/ul?q={encoded}&navigate=yes',
        },
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def quote_send_for_approval(request, pk):
    """Phase 20 v4 (v3.17.270): route a quote through a PSAApproval chain.

    POST fields:
      - threshold: optional; quotes at or above this dollar total get a
                   2-stage manager → director chain. Below, single stage.
                   Empty / 0 means single stage regardless of total.
    """
    from core.models import SystemSetting
    org = get_request_organization(request)
    qs = Quote.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)

    threshold_raw = (request.POST.get('threshold') or '').strip()
    threshold = None
    if threshold_raw:
        try:
            threshold = float(threshold_raw)
        except (TypeError, ValueError):
            threshold = None
    if threshold is None or threshold <= 0:
        # Fall back to SystemSetting.invoice_approval_threshold_total
        # which the org already configured for invoice gating.
        try:
            ss = SystemSetting.get_settings()
            threshold = float(ss.invoice_approval_threshold_total or 0) or None
        except Exception:
            threshold = None

    chain = item.send_for_approval(user=request.user,
                                    default_threshold_total=threshold)
    n = len(chain)
    AuditLog.log(
        user=request.user, action='create',
        organization=org or item.organization,
        object_type='psa.Quote', object_id=item.pk,
        object_repr=item.quote_number,
        description=f'Routed quote {item.quote_number} through {n}-stage approval chain',
        ip_address=_client_ip(request), path=request.path,
    )
    if n == 1 and chain[0].status == 'pending':
        messages.success(request, f'Sent {item.quote_number} for single-stage approval.')
    else:
        messages.success(request,
                         f'Sent {item.quote_number} for {n}-stage approval routing.')
    return redirect('psa:quote_detail', pk=item.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_expense_add(request, ticket_number):
    org = get_request_organization(request)
    qs = Ticket.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)

    description = (request.POST.get('description') or '').strip()
    if not description:
        messages.error(request, 'Description required.')
        return redirect('psa:ticket_detail', ticket_number=ticket_number)
    try:
        amount = float(request.POST.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0

    expense = TicketExpense.objects.create(
        ticket=ticket, user=request.user,
        category=request.POST.get('category') or 'other',
        description=description[:300],
        amount=amount,
        currency=(request.POST.get('currency') or 'USD')[:8],
        incurred_on=request.POST.get('incurred_on') or timezone.now().date(),
        is_billable=request.POST.get('is_billable') == 'on',
        is_reimbursable=request.POST.get('is_reimbursable') == 'on',
        receipt_file=request.FILES.get('receipt_file'),
    )
    AuditLog.log(
        user=request.user, action='create',
        organization=ticket.organization,
        object_type='psa.TicketExpense', object_id=expense.pk,
        object_repr=expense.description,
        description=f'Added {expense.amount} {expense.currency} expense to {ticket.ticket_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Expense added: {amount:.2f} {expense.currency}.')
    return redirect('psa:ticket_detail', ticket_number=ticket_number)


# ---------------------------------------------------------------------------
# Project tasks (Workstream 3 expansion)
# ---------------------------------------------------------------------------


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def project_task_add(request, pk):
    org = get_request_organization(request)
    qs = Project.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    project = get_object_or_404(qs, pk=pk)

    title = (request.POST.get('title') or '').strip()
    if not title:
        messages.error(request, 'Task title is required.')
        return redirect('psa:project_detail', pk=project.pk)

    # v3.17.129 — admins can pick the task's assignee from any eligible tech
    # in the project's org (falls back to creator-assignment if not allowed).
    initial_assignee = None
    posted_assignee = (request.POST.get('assigned_to') or '').strip()
    if posted_assignee and _can_assign(request, project.organization):
        from django.contrib.auth.models import User
        try:
            cand = User.objects.get(pk=int(posted_assignee), is_active=True)
            eligible_ids = set(
                _eligible_assignees(project.organization).values_list('id', flat=True)
            )
            if cand.id in eligible_ids:
                initial_assignee = cand
        except (User.DoesNotExist, ValueError, TypeError):
            pass

    from .models import ProjectTask
    ProjectTask.objects.create(
        project=project,
        title=title[:300],
        description=(request.POST.get('description') or '').strip()[:5000],
        is_milestone=request.POST.get('is_milestone') == 'on',
        due_date=request.POST.get('due_date') or None,
        created_by=request.user,
        assigned_to=initial_assignee,
        sort_order=project.tasks.count(),
    )
    messages.success(request, f'Added task "{title}".')
    return redirect('psa:project_detail', pk=project.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def project_task_update(request, task_pk):
    from .models import ProjectTask
    org = get_request_organization(request)
    qs = ProjectTask.objects.select_related('project')
    if org is not None:
        qs = qs.filter(project__organization=org)
    task = get_object_or_404(qs, pk=task_pk)

    new_status = request.POST.get('status')
    changed = False
    if new_status in {'todo', 'in_progress', 'blocked', 'done', 'cancelled'}:
        task.status = new_status
        changed = True
    # v3.17.129 — admins can reassign a project task. Posting `assigned_to`
    # with empty value clears the assignee.
    if 'assigned_to' in request.POST and _can_assign(request, task.project.organization):
        from django.contrib.auth.models import User
        posted = (request.POST.get('assigned_to') or '').strip()
        if posted in ('', '0', 'unassigned'):
            task.assigned_to = None
            changed = True
        else:
            try:
                cand = User.objects.get(pk=int(posted), is_active=True)
                eligible_ids = set(
                    _eligible_assignees(task.project.organization).values_list('id', flat=True)
                )
                if cand.id in eligible_ids:
                    task.assigned_to = cand
                    changed = True
            except (User.DoesNotExist, ValueError, TypeError):
                pass
    if changed:
        task.save()
        messages.success(request, f'Updated "{task.title}".')
    return redirect('psa:project_detail', pk=task.project.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def project_task_delete(request, task_pk):
    from .models import ProjectTask
    org = get_request_organization(request)
    qs = ProjectTask.objects.select_related('project')
    if org is not None:
        qs = qs.filter(project__organization=org)
    task = get_object_or_404(qs, pk=task_pk)
    project_pk = task.project_id
    title = task.title
    task.delete()
    messages.success(request, f'Deleted "{title}".')
    return redirect('psa:project_detail', pk=project_pk)


# ---------------------------------------------------------------------------
# Workflow Rules (Workstream 9)
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
def workflow_rule_list(request):
    """Workflow rules are MSP-level config — they apply to ANY ticket. No
    client filter, even when a client is currently in scope."""
    from .models import WorkflowRule
    qs = WorkflowRule.objects.select_related('organization').order_by('sort_order', 'name')
    return render(request, 'psa/workflow_rule_list.html', {
        'rules': qs[:200],
    })


@login_required
@require_psa_enabled
def workflow_template_list(request):
    """Phase 14 v9 (v3.17.288): list workflow rule templates and offer
    one-click instantiation against the active org."""
    from .models import WorkflowRuleTemplate
    from core.models import Organization
    qs = WorkflowRuleTemplate.objects.order_by('category', 'name')
    return render(request, 'psa/workflow_template_list.html', {
        'templates': qs,
        'organizations': Organization.objects.filter(is_active=True)
                          .order_by('name')[:500],
    })


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['POST'])
def workflow_template_instantiate(request, pk):
    """Phase 14 v9 (v3.17.288): clone a template into a new
    WorkflowRule. Optional `organization` POST field scopes it to a
    specific client; blank = MSP-wide."""
    from .models import WorkflowRuleTemplate
    from core.models import Organization
    template = get_object_or_404(WorkflowRuleTemplate, pk=pk)

    org = None
    org_id = request.POST.get('organization')
    if org_id:
        org = Organization.objects.filter(pk=org_id).first()

    name_override = (request.POST.get('name') or '').strip() or None
    rule = template.instantiate(
        organization=org, name_override=name_override,
        created_by=request.user,
    )
    AuditLog.log(
        user=request.user, action='create',
        organization=org or rule.organization,
        object_type='psa.WorkflowRule', object_id=rule.pk,
        object_repr=rule.name,
        description=f'Instantiated rule from template "{template.name}"',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Created rule "{rule.name}" from template.')
    return redirect('psa:workflow_rule_edit', pk=rule.pk)


@login_required
@require_psa_enabled
def workflow_suggestion_list(request):
    """Phase 14 v13 (v3.17.290): list pending workflow suggestions
    generated by the OPTIONAL AI engine. Shows summary + suggested
    payload + accept/dismiss buttons. The list is empty when
    `psa_ai_enabled=False` so admins on AI-disabled installs see
    nothing."""
    from .models import WorkflowSuggestion
    from core.models import SystemSetting
    ss = SystemSetting.get_settings()
    ai_enabled = bool(getattr(ss, 'psa_ai_enabled', False))
    qs = WorkflowSuggestion.objects.order_by('-generated_at')
    if ai_enabled:
        qs = qs.filter(status='pending')
    else:
        qs = qs.none()
    return render(request, 'psa/workflow_suggestion_list.html', {
        'suggestions': qs[:100],
        'ai_enabled': ai_enabled,
    })


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['POST'])
def workflow_suggestion_decide(request, pk):
    """Accept or dismiss a workflow suggestion. POST `action=accept|dismiss`."""
    from .models import WorkflowSuggestion
    from core.models import SystemSetting
    ss = SystemSetting.get_settings()
    if not getattr(ss, 'psa_ai_enabled', False):
        messages.error(request, 'AI features are disabled in System Settings.')
        return redirect('psa:workflow_suggestion_list')
    s = get_object_or_404(WorkflowSuggestion, pk=pk)
    action = (request.POST.get('action') or '').strip()
    if action == 'accept':
        rule = s.accept(user=request.user)
        AuditLog.log(
            user=request.user, action='create',
            organization=rule.organization,
            object_type='psa.WorkflowRule', object_id=rule.pk,
            object_repr=rule.name,
            description=f'Accepted suggestion #{s.pk}: {s.summary[:200]}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Accepted suggestion → rule "{rule.name}".')
        return redirect('psa:workflow_rule_edit', pk=rule.pk)
    elif action == 'dismiss':
        s.dismiss(user=request.user)
        messages.info(request, 'Suggestion dismissed.')
    else:
        messages.error(request, 'Pick accept or dismiss.')
    return redirect('psa:workflow_suggestion_list')


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def workflow_rule_form(request, pk=None):
    """Create/edit an MSP-level workflow rule. The rule's organization is
    optional — leave blank to apply to every client's tickets, or pick a
    specific client to scope it. No 'pick a client first' requirement."""
    from .models import WorkflowRule
    from core.models import Organization
    import json as _json
    item = get_object_or_404(WorkflowRule, pk=pk) if pk else None

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        trigger = request.POST.get('trigger') or ''
        if not name or trigger not in {c[0] for c in WorkflowRule.TRIGGER_CHOICES}:
            messages.error(request, 'Name and a valid trigger are required.')
            return redirect(request.path)
        try:
            conditions = _json.loads(request.POST.get('conditions') or '{}')
        except _json.JSONDecodeError:
            messages.error(request, 'Conditions must be valid JSON.')
            return redirect(request.path)
        try:
            actions = _json.loads(request.POST.get('actions') or '[]')
        except _json.JSONDecodeError:
            messages.error(request, 'Actions must be valid JSON.')
            return redirect(request.path)
        if not isinstance(conditions, dict):
            messages.error(request, 'Conditions must be a JSON object.')
            return redirect(request.path)
        if not isinstance(actions, list):
            messages.error(request, 'Actions must be a JSON list.')
            return redirect(request.path)

        # Optional client scope
        scoped_org = None
        org_id = (request.POST.get('organization') or '').strip()
        if org_id:
            try:
                scoped_org = Organization.objects.get(pk=int(org_id))
            except (Organization.DoesNotExist, ValueError):
                scoped_org = None

        if item is None:
            item = WorkflowRule(name=name, trigger=trigger, created_by=request.user,
                                organization=scoped_org)
        else:
            item.name = name
            item.trigger = trigger
            item.organization = scoped_org
        item.description = (request.POST.get('description') or '').strip()
        item.conditions = conditions
        item.actions = actions
        item.is_active = request.POST.get('is_active') == 'on'
        try:
            item.sort_order = max(0, int(request.POST.get('sort_order') or 0))
        except ValueError:
            item.sort_order = 0
        item.save()
        messages.success(request, f'Saved rule "{item.name}".')
        return redirect('psa:workflow_rule_list')

    return render(request, 'psa/workflow_rule_form.html', {
        'item': item,
        'trigger_choices': WorkflowRule.TRIGGER_CHOICES,
        'conditions_pretty': _json.dumps(item.conditions if item else {}, indent=2),
        'actions_pretty': _json.dumps(item.actions if item else [], indent=2),
        'conditions_json': _json.dumps(item.conditions if item else {}),
        'actions_json': _json.dumps(item.actions if item else []),
        'client_orgs': Organization.objects.filter(is_active=True).order_by('name'),
        'priorities': TicketPriority.objects.all().order_by('sort_order'),
        'queues': Queue.objects.filter(is_active=True).order_by('name'),
        'statuses': TicketStatus.objects.all().order_by('sort_order'),
    })


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['POST'])
def workflow_rule_delete(request, pk):
    from .models import WorkflowRule
    org = get_request_organization(request)
    qs = WorkflowRule.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    name = item.name
    item.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect('psa:workflow_rule_list')


# ---------------------------------------------------------------------------
# Dispatch board — weekly grid of assigned tickets per tech
# ---------------------------------------------------------------------------


def _dispatch_priority_key(ticket):
    """
    Phase 11.1: dispatch sort key — most urgent first.

    Combines (a) the priority's ``sort_order`` (lower = higher priority;
    P1 typically 0) and (b) the soonest applicable due timestamp. Tickets
    with no due date sink to the bottom within their priority band via
    a sentinel "has-no-due" flag in the sort tuple (avoids needing a
    far-future datetime sentinel and the tz-handling that goes with it).
    """
    sort_order = ticket.priority.sort_order if ticket.priority_id else 9999
    due = ticket.resolution_due_at or ticket.first_response_due_at
    # Tuple: (priority, no_due_flag, due). False sorts before True so
    # tickets WITH a due date come first within the priority band.
    return (sort_order, due is None, due)


def _dispatch_conflicts(tech_user, ticket):
    """
    Phase 11.2: returns a list of one-line conflict warnings for
    assigning ``ticket`` to ``tech_user``. Empty list = no conflicts.
    The caller (dispatch_assign / dispatch_board) decides whether to
    block, warn, or pass through.

    Conflicts checked:
      - **PTO**: approved ``resourcing.LeaveRequest`` covering the
        ticket's due date.
      - **Calendar overlap**: another open ticket already assigned to
        the same tech with a due date inside a ±2-hour window.
    """
    warnings = []
    if tech_user is None:
        return warnings

    due = ticket.resolution_due_at or ticket.first_response_due_at
    if due is None:
        return warnings  # no due date → no schedulable conflict

    # PTO check via resourcing.LeaveRequest. Wrapped in try/except so the
    # poller / dispatch view doesn't break if resourcing isn't installed
    # in a slim deployment.
    try:
        from resourcing.models import LeaveRequest
        target_date = due.date() if hasattr(due, 'date') else due
        if LeaveRequest.is_user_on_leave(tech_user, target_date):
            warnings.append(
                f'PTO conflict: {tech_user.username} is on approved leave on '
                f'{target_date.isoformat()}'
            )
    except Exception:  # noqa: BLE001 — resourcing may be absent
        pass

    # Calendar overlap. Window = ±2 hours. Excludes the ticket itself
    # and any closed/cancelled tickets.
    from datetime import timedelta
    overlap_start = due - timedelta(hours=2)
    overlap_end = due + timedelta(hours=2)
    other_qs = (
        Ticket.objects
        .filter(assigned_to=tech_user)
        .exclude(pk=ticket.pk)
        .filter(status__is_terminal=False)
        .select_related('status')
    )
    for other in other_qs:
        other_due = other.resolution_due_at or other.first_response_due_at
        if other_due and overlap_start <= other_due <= overlap_end:
            warnings.append(
                f'Calendar conflict: {tech_user.username} also on '
                f'{other.ticket_number} due {other_due.strftime("%H:%M %Z")}'.rstrip()
            )
    return warnings


@login_required
@require_psa_enabled
def dispatch_board(request):
    """
    Dispatch board: 7-day grid + an Other column for tickets outside the
    window or without a due date. Shows ALL tickets (open + closed) so
    nothing is hidden — closed/resolved still appear so you can see what
    a tech wrapped up. Unassigned tickets get their own row at the top.
    Overdue open tickets surface in a separate panel above the grid.

    Phase 11.1 additions:
      - "SLA at risk" panel: open tickets due within the next 4 hours but
        not yet overdue. Surfaced above the grid alongside `overdue`.
      - All cells (assigned, unassigned-by-day, overdue, sla_burn) are
        sorted by priority + SLA proximity instead of creation order.
    """
    from datetime import date, timedelta

    org = get_request_organization(request)
    qs = Ticket.objects.select_related('assigned_to', 'priority', 'status', 'organization')
    if org is not None:
        qs = qs.filter(organization=org)

    days = []
    today = date.today()
    for i in range(7):
        d = today + timedelta(days=i)
        days.append(d)

    # Phase 11.1: 4-hour SLA-burn window. Open tickets due inside this
    # window but not yet overdue surface in a dedicated panel.
    now = timezone.now()
    sla_burn_cutoff = now + timedelta(hours=4)

    # Cells use day-key for the 7 columns + the literal string 'other' for
    # tickets without a due date OR with a due date outside the window.
    OTHER = 'other'
    cells = {}
    techs = {}
    unassigned_by_day = {d: [] for d in days}
    unassigned_by_day[OTHER] = []
    overdue = []
    sla_burn = []

    for t in qs.order_by('-created_at')[:1000]:
        due = t.resolution_due_at or t.first_response_due_at
        is_open = not (t.status_id and t.status.is_terminal)
        bucket = OTHER  # default for no-due-date or outside window
        if due:
            d_local = timezone.localtime(due).date() if hasattr(due, 'date') else due
            if d_local < today and is_open:
                overdue.append(t)
                continue
            # Phase 11.1: SLA-at-risk surfacing — tickets whose due time
            # is within the next 4 hours but not already overdue. They
            # still appear in the grid below; this is an added view.
            if is_open and now <= due <= sla_burn_cutoff:
                sla_burn.append(t)
            if today <= d_local <= today + timedelta(days=6):
                bucket = d_local
        if t.assigned_to_id:
            techs[t.assigned_to_id] = t.assigned_to
            cells.setdefault((t.assigned_to_id, bucket), []).append(t)
        else:
            unassigned_by_day[bucket].append(t)

    # Phase 11.1: sort every list of tickets by priority + SLA proximity
    # so the most urgent surfaces at the top of each lane.
    overdue.sort(key=_dispatch_priority_key)
    sla_burn.sort(key=_dispatch_priority_key)
    for bucket_list in unassigned_by_day.values():
        bucket_list.sort(key=_dispatch_priority_key)
    for cell_list in cells.values():
        cell_list.sort(key=_dispatch_priority_key)

    # Admins see ALL eligible techs (org members + staff/superusers) as rows
    # so they can drag a card to a tech who currently has zero tickets.
    # Non-admins still only see techs who have tickets in the visible scope.
    can_assign = _can_assign(request, org)
    if can_assign:
        for u in _eligible_assignees(org):
            techs.setdefault(u.id, u)

    techs_sorted = sorted(techs.values(), key=lambda u: (u.username or '').lower())
    rows = []
    for u in techs_sorted:
        rows.append({
            'tech': u,
            'cells': [cells.get((u.id, d), []) for d in days],
            'other': cells.get((u.id, OTHER), []),
        })

    # Phase 2.3 — skill ranking. For each ticket card, top 5 candidates
    # by skill+availability score. Only computed for admins who can assign.
    skill_rankings = {}
    if can_assign:
        try:
            from resourcing.views import rank_techs_for_ticket
            seen = set()
            all_tickets_in_view = []
            for bucket_list in cells.values():
                for t in bucket_list:
                    if t.pk not in seen:
                        seen.add(t.pk); all_tickets_in_view.append(t)
            for bucket_list in unassigned_by_day.values():
                for t in bucket_list:
                    if t.pk not in seen:
                        seen.add(t.pk); all_tickets_in_view.append(t)
            for t in overdue:
                if t.pk not in seen:
                    seen.add(t.pk); all_tickets_in_view.append(t)
            skill_rankings = {
                t.pk: rank_techs_for_ticket(t)[:5]
                for t in all_tickets_in_view
            }
        except Exception:
            skill_rankings = {}

    return render(request, 'psa/dispatch_board.html', {
        'days': days,
        'rows': rows,
        'unassigned_by_day': [unassigned_by_day[d] for d in days],
        'unassigned_other': unassigned_by_day[OTHER],
        'overdue': overdue,
        'sla_burn': sla_burn,  # Phase 11.1
        'can_assign': can_assign,
        'skill_rankings': skill_rankings,
    })


# ---------------------------------------------------------------------------
# Phase 8 — Invoices + Payments + Accounting integration handoff
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
def invoice_list(request):
    from .models import Invoice
    org = get_request_organization(request)
    qs = Invoice.objects.select_related('client_org', 'created_by')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    status = request.GET.get('status')
    if status in {'draft', 'sent', 'partial', 'paid', 'overdue', 'void'}:
        qs = qs.filter(status=status)
    return render(request, 'psa/invoice_list.html', {
        'invoices': qs.order_by('-invoice_date', '-created_at')[:200],
        'status_filter': status or '',
    })


@login_required
@require_psa_enabled
def invoice_detail(request, pk):
    from .models import Invoice
    org = get_request_organization(request)
    qs = Invoice.objects.select_related('client_org', 'source_quote', 'source_ticket', 'source_contract')
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    return render(request, 'psa/invoice_detail.html', {
        'item': item,
        'line_items': item.line_items.all(),
        'payments': item.payments.all(),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def invoice_form(request, pk=None):
    from .models import Invoice, InvoiceLineItem
    from core.models import Organization, SystemSetting
    from datetime import date as _date
    if pk:
        item = get_object_or_404(Invoice, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    def _render(selected_org_id=None):
        settings = SystemSetting.get_settings()
        default_tax_rate = settings.psa_default_tax_rate if not item else item.tax_rate
        default_currency = settings.psa_default_currency if not item else item.currency
        return render(request, 'psa/invoice_form.html', {
            'item': item,
            'client_orgs': client_orgs,
            'status_choices': Invoice.STATUS_CHOICES,
            'line_items': item.line_items.all() if item else [],
            'default_tax_rate': default_tax_rate,
            'default_currency': default_currency,
            'selected_client_org_id': selected_org_id if selected_org_id is not None
                                       else (item.organization_id if item else (org.pk if org else None)),
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('client_org_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid client.')
                return _render()
        else:
            item_org = org

        if item_org is None:
            messages.error(request, 'Please choose a client for this invoice.')
            return _render()

        title = (request.POST.get('title') or '').strip()
        client_org_id = request.POST.get('client_org')
        if not title or not client_org_id:
            messages.error(request, 'Title and client are required.')
            return _render(selected_org_id=item_org.pk)
        try:
            client_org = Organization.objects.get(pk=client_org_id)
        except Organization.DoesNotExist:
            messages.error(request, 'Client not found.')
            return _render(selected_org_id=item_org.pk)

        if item is None:
            item = Invoice(organization=item_org, client_org=client_org, title=title,
                           invoice_date=_date.today(), created_by=request.user)
        else:
            item.organization = item_org
            item.client_org = client_org
            item.title = title
        item.description = (request.POST.get('description') or '').strip()
        item.status = request.POST.get('status') or 'draft'
        item.invoice_date = request.POST.get('invoice_date') or item.invoice_date
        item.due_date = request.POST.get('due_date') or None
        item.currency = (request.POST.get('currency') or 'USD')[:8]
        try:
            item.tax_rate = request.POST.get('tax_rate') or 0
        except (TypeError, ValueError):
            item.tax_rate = 0
        item.notes = (request.POST.get('notes') or '').strip()
        item.save()

        # Replace line items
        descs = request.POST.getlist('li_description')
        qtys = request.POST.getlist('li_quantity')
        prices = request.POST.getlist('li_unit_price')
        if descs:
            item.line_items.all().delete()
            for i, (d, q, p) in enumerate(zip(descs, qtys, prices)):
                if not (d or '').strip():
                    continue
                try:
                    qf = float(q or 1)
                    pf = float(p or 0)
                except ValueError:
                    qf, pf = 1, 0
                InvoiceLineItem.objects.create(
                    invoice=item, sort_order=i,
                    description=d.strip()[:300], quantity=qf, unit_price=pf,
                )
        item.recompute_totals()
        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=item_org,
            object_type='psa.Invoice', object_id=item.pk,
            object_repr=item.invoice_number,
            description=f'{"Updated" if pk else "Created"} invoice {item.invoice_number}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Saved {item.invoice_number}.')
        return redirect('psa:invoice_detail', pk=item.pk)

    return _render()


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def invoice_from_ticket(request, ticket_number):
    """Generate a draft invoice from a ticket's billable time + expenses."""
    from .models import Invoice, InvoiceLineItem
    from datetime import date as _date
    org = get_request_organization(request)
    qs = Ticket.objects.select_related('organization')
    if org is not None:
        qs = qs.filter(organization=org)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)

    # Default rate from contract, fallback to 0
    contract = Contract.for_ticket(ticket)
    rate = float(contract.hourly_rate) if contract else 0.0

    invoice = Invoice.objects.create(
        organization=org or ticket.organization,
        client_org=ticket.organization,
        title=f'Invoice for {ticket.ticket_number} — {ticket.subject}'[:300],
        description=f'Billable time + expenses for ticket {ticket.ticket_number}',
        invoice_date=_date.today(),
        source_ticket=ticket,
        source_contract=contract,
        created_by=request.user,
    )
    sort_order = 0
    for te in ticket.time_entries.filter(is_billable=True):
        if not te.duration_minutes:
            continue
        InvoiceLineItem.objects.create(
            invoice=invoice, sort_order=sort_order,
            description=f'Time: {te.notes or "work"}'[:300],
            quantity=round(te.duration_minutes / 60.0, 2),
            unit_price=rate,
            source='time', source_id=str(te.pk),
        )
        sort_order += 1
    for e in ticket.expenses.filter(is_billable=True):
        InvoiceLineItem.objects.create(
            invoice=invoice, sort_order=sort_order,
            description=f'Expense: {e.description}'[:300],
            quantity=1, unit_price=float(e.amount),
            source='expense', source_id=str(e.pk),
        )
        sort_order += 1
    invoice.recompute_totals()
    messages.success(request, f'Draft invoice {invoice.invoice_number} created from {ticket.ticket_number}.')
    return redirect('psa:invoice_detail', pk=invoice.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def payment_add(request, invoice_pk):
    from .models import Invoice, Payment
    from datetime import date as _date
    org = get_request_organization(request)
    qs = Invoice.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    invoice = get_object_or_404(qs, pk=invoice_pk)
    try:
        amount = float(request.POST.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        messages.error(request, 'Amount must be positive.')
        return redirect('psa:invoice_detail', pk=invoice.pk)
    Payment.objects.create(
        invoice=invoice, amount=amount,
        paid_on=request.POST.get('paid_on') or _date.today(),
        method=request.POST.get('method') or 'ach',
        reference=(request.POST.get('reference') or '')[:120],
        notes=(request.POST.get('notes') or '').strip(),
        created_by=request.user,
    )
    messages.success(request, f'Payment of {amount:.2f} recorded.')
    return redirect('psa:invoice_detail', pk=invoice.pk)


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['POST'])
def invoice_approve(request, pk):
    """
    Phase 36 v2 (v3.17.228): clear the pre-invoice approval gate. Sets
    `approved_by` + `approved_at`, clears `requires_approval`. Logs the
    action to AuditLog. Restricted to admin/owner roles.
    """
    from .models import Invoice
    org = get_request_organization(request)
    qs = Invoice.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    if not item.requires_approval:
        messages.info(request, f'Invoice {item.invoice_number} does not require approval.')
        return redirect('psa:invoice_detail', pk=item.pk)
    item.approve(user=request.user)
    AuditLog.log(
        user=request.user, action='update',
        organization=org or item.organization,
        object_type='psa.Invoice', object_id=item.pk,
        object_repr=item.invoice_number,
        description=f'Approved invoice {item.invoice_number} (was: {item.approval_reason or "manual hold"})',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Approved invoice {item.invoice_number}.')
    return redirect('psa:invoice_detail', pk=item.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def invoice_request_approval(request, pk):
    """
    Phase 36 v2 (v3.17.228): manually flag an invoice as requiring
    approval before it can be sent. Used when the threshold-based auto
    flag missed an edge case (e.g. unusual customer, billing dispute).
    """
    from .models import Invoice
    org = get_request_organization(request)
    qs = Invoice.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    reason = (request.POST.get('reason') or 'Manual hold').strip()[:200]
    item.requires_approval = True
    item.approval_reason = reason
    item.approved_by = None
    item.approved_at = None
    item.save(update_fields=['requires_approval', 'approval_reason',
                             'approved_by', 'approved_at', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=org or item.organization,
        object_type='psa.Invoice', object_id=item.pk,
        object_repr=item.invoice_number,
        description=f'Flagged invoice {item.invoice_number} for approval: {reason}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Invoice {item.invoice_number} flagged for approval.')
    return redirect('psa:invoice_detail', pk=item.pk)


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['POST'])
def invoice_credit_memo(request, pk):
    """Phase 27 v3 (v3.17.264): issue a credit memo against this invoice.

    POST fields:
      - reason: optional, captured on the new memo's description
      - amount: optional decimal; when set, creates a single-line lump-sum
                credit. When blank, copies all source line items with
                negated unit_price (full credit).

    Forbidden against credit memos themselves (model raises ValueError).
    """
    from .models import Invoice
    org = get_request_organization(request)
    qs = Invoice.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    invoice = get_object_or_404(qs, pk=pk)

    reason = (request.POST.get('reason') or '').strip()[:500]
    amount_raw = (request.POST.get('amount') or '').strip()
    amount = None
    if amount_raw:
        try:
            from decimal import Decimal as _D
            amount = _D(amount_raw)
            if amount <= 0:
                raise ValueError('Amount must be positive')
        except Exception as e:
            messages.error(request, f'Invalid credit amount: {e}')
            return redirect('psa:invoice_detail', pk=invoice.pk)

    try:
        memo = invoice.create_credit_memo(user=request.user, reason=reason, amount=amount)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('psa:invoice_detail', pk=invoice.pk)

    AuditLog.log(
        user=request.user, action='create',
        organization=org or invoice.organization,
        object_type='psa.Invoice', object_id=memo.pk,
        object_repr=memo.invoice_number,
        description=f'Issued credit memo {memo.invoice_number} against {invoice.invoice_number} (total {memo.total})',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Credit memo {memo.invoice_number} created.')
    return redirect('psa:invoice_detail', pk=memo.pk)


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['POST'])
def invoice_push_to_accounting(request, pk):
    """Push the invoice to the configured accounting provider for this org."""
    from .models import Invoice
    from integrations.models import AccountingConnection
    from integrations.providers.accounting import get_accounting_provider
    org = get_request_organization(request)
    qs = Invoice.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    invoice = get_object_or_404(qs, pk=pk)

    # Phase 36 v2: block pushes when the approval gate is set.
    if invoice.requires_approval:
        messages.error(
            request,
            f'Invoice {invoice.invoice_number} requires approval before push '
            f'({invoice.approval_reason or "no reason given"}).',
        )
        return redirect('psa:invoice_detail', pk=invoice.pk)

    # v3.17.526: refuse to push an invoice that already carries a provider id.
    # The push is not idempotent — the provider creates a new invoice on every
    # call — so a double-click, a browser resend or an impatient second click
    # put duplicate invoices in front of the client's accounts payable. The
    # reconciliation report at /reports/accounting-reconciliation/ has only ever
    # caught these *after* they existed in the accounting system.
    #
    # A re-push is still possible (the invoice was deleted provider-side, say)
    # but it now has to be asked for explicitly rather than being one stray
    # click away.
    if invoice.accounting_external_id and not request.POST.get('force'):
        pushed = invoice.pushed_to_accounting_at
        # `accounting_provider` is a plain CharField with no choices, so there
        # is no get_..._display() to call — format the stored slug instead.
        where = (invoice.accounting_provider or '').replace('_', ' ').title() \
            or 'an accounting provider'
        messages.warning(
            request,
            f'Invoice {invoice.invoice_number} was already pushed to {where} '
            f'as id {invoice.accounting_external_id}'
            + (f' on {pushed:%Y-%m-%d %H:%M}' if pushed else '')
            + '. Pushing again would create a second invoice there. Use '
              '"Re-push" if that is genuinely what you want.',
        )
        return redirect('psa:invoice_detail', pk=invoice.pk)

    # Phase 27 v7 (v3.17.279): when the invoice is pinned to a specific
    # connection (multi-entity / multi-book), use that. Otherwise fall
    # back to the first sync-enabled connection on the org.
    conn = invoice.target_connection
    if conn is not None and not (conn.is_active and conn.sync_enabled):
        messages.error(
            request,
            f'Pinned connection "{conn.name}" is inactive or sync-disabled. '
            f'Edit it in Integrations or unpin the invoice.',
        )
        return redirect('psa:invoice_detail', pk=invoice.pk)
    if conn is None:
        conn = AccountingConnection.objects.filter(
            organization=invoice.organization,
            is_active=True, sync_enabled=True,
        ).first()
    if conn is None:
        messages.error(request, 'No active accounting connection with sync enabled. Configure one in Integrations.')
        return redirect('psa:invoice_detail', pk=invoice.pk)

    provider = get_accounting_provider(conn)
    if provider is None:
        messages.error(request, 'Provider class not registered.')
        return redirect('psa:invoice_detail', pk=invoice.pk)

    try:
        result = provider.push_invoice(invoice)
    except Exception as exc:
        messages.error(request, f'Push failed: {exc}')
        return redirect('psa:invoice_detail', pk=invoice.pk)

    if result.get('success'):
        messages.success(request, f'Pushed to {conn.get_provider_type_display()} (id {result.get("invoice_id")}).')
    else:
        messages.error(request, f'Push failed: {result.get("error", "unknown")}')
    return redirect('psa:invoice_detail', pk=invoice.pk)


# ---------------------------------------------------------------------------
# Phase 9 — PDF downloads + customer email for quotes and invoices
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
def quote_pdf(request, pk):
    from django.http import HttpResponse
    from .pdf import render_quote_pdf
    org = get_request_organization(request)
    qs = Quote.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    quote = get_object_or_404(qs.select_related('client_org', 'organization'), pk=pk)
    sign_url = request.build_absolute_uri(
        f'/portal/quote/{quote.customer_token}/sign/'
    ) if quote.customer_token and quote.status not in ('accepted', 'rejected') else ''
    pdf_bytes = render_quote_pdf(quote, sign_url=sign_url)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') else 'inline'
    resp['Content-Disposition'] = f'{disposition}; filename="{quote.quote_number}.pdf"'
    return resp


@login_required
@require_psa_enabled
def invoice_pdf(request, pk):
    from django.http import HttpResponse
    from .pdf import render_invoice_pdf
    org = get_request_organization(request)
    qs = Invoice.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    invoice = get_object_or_404(qs.select_related('client_org', 'organization'), pk=pk)
    pdf_bytes = render_invoice_pdf(invoice)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') else 'inline'
    resp['Content-Disposition'] = f'{disposition}; filename="{invoice.invoice_number}.pdf"'
    return resp


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def quote_email(request, pk):
    from .pdf import email_quote
    org = get_request_organization(request)
    qs = Quote.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    quote = get_object_or_404(qs.select_related('client_org', 'organization'), pk=pk)
    recipient = (request.POST.get('recipient') or '').strip()
    subject = (request.POST.get('subject') or '').strip()
    body = (request.POST.get('body') or '').strip()
    if not recipient or '@' not in recipient:
        messages.error(request, 'Provide a valid recipient email.')
        return redirect('psa:quote_list')
    try:
        ok = email_quote(quote, recipient=recipient, subject=subject, body=body, request=request)
    except Exception as exc:
        messages.error(request, f'Email failed: {exc}')
        return redirect('psa:quote_list')
    if ok:
        # Mark sent if it was draft
        if quote.status == 'draft':
            quote.status = 'sent'
            quote.sent_at = timezone.now()
            quote.save(update_fields=['status', 'sent_at', 'updated_at'])
        AuditLog.log(
            user=request.user, action='update',
            organization=quote.organization,
            object_type='psa.Quote', object_id=quote.pk,
            object_repr=quote.quote_number,
            description=f'Emailed quote {quote.quote_number} to {recipient}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Sent quote {quote.quote_number} to {recipient}.')
    else:
        messages.error(request, 'Email send returned 0 recipients.')
    return redirect('psa:quote_list')


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def invoice_email(request, pk):
    from .pdf import email_invoice
    org = get_request_organization(request)
    qs = Invoice.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    invoice = get_object_or_404(qs.select_related('client_org', 'organization'), pk=pk)
    recipient = (request.POST.get('recipient') or '').strip()
    subject = (request.POST.get('subject') or '').strip()
    body = (request.POST.get('body') or '').strip()
    if not recipient or '@' not in recipient:
        messages.error(request, 'Provide a valid recipient email.')
        return redirect('psa:invoice_detail', pk=invoice.pk)
    try:
        ok = email_invoice(invoice, recipient=recipient, subject=subject, body=body)
    except Exception as exc:
        messages.error(request, f'Email failed: {exc}')
        return redirect('psa:invoice_detail', pk=invoice.pk)
    if ok:
        if invoice.status == 'draft':
            invoice.status = 'sent'
            invoice.sent_at = timezone.now()
            invoice.save(update_fields=['status', 'sent_at', 'updated_at'])
        AuditLog.log(
            user=request.user, action='update',
            organization=invoice.organization,
            object_type='psa.Invoice', object_id=invoice.pk,
            object_repr=invoice.invoice_number,
            description=f'Emailed invoice {invoice.invoice_number} to {recipient}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Sent invoice {invoice.invoice_number} to {recipient}.')
    else:
        messages.error(request, 'Email send returned 0 recipients.')
    return redirect('psa:invoice_detail', pk=invoice.pk)


@login_required
@require_psa_enabled
def quote_detail(request, pk):
    from accounts.permission_utils import user_has_perm
    org = get_request_organization(request)
    qs = Quote.objects.select_related('client_org', 'organization', 'created_by')
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    return render(request, 'psa/quote_detail.html', {
        'item': item,
        'line_items': item.line_items.all(),
        'can_create_po': user_has_perm(request.user, 'procurement_create_po'),
        'linked_pos': item.purchase_orders.all().order_by('-created_at'),
    })


# ---------------------------------------------------------------------------
# Phase 10 — Client account view + Charges + Aging report
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
def client_account(request, org_id):
    """Per-client account summary: balance, aging, invoices, charges,
    payments, unbilled time + expenses ready to invoice."""
    from .models import Charge, Invoice, Payment, get_psa_balance
    from core.models import Organization
    client = get_object_or_404(Organization, pk=org_id)

    org = get_request_organization(request)
    summary = get_psa_balance(client, msp_org=org)
    invoices = Invoice.objects.filter(client_org=client)
    charges = Charge.objects.filter(client_org=client)
    if org is not None:
        invoices = invoices.filter(organization=org)
        charges = charges.filter(organization=org)

    payments = Payment.objects.filter(invoice__client_org=client)
    if org is not None:
        payments = payments.filter(invoice__organization=org)

    # Unbilled work — time entries on this client's tickets that are
    # billable AND don't have an invoice line linked to them yet.
    unbilled_time = TicketTimeEntry.objects.filter(
        ticket__organization=client, is_billable=True,
    ).exclude(duration_minutes=0).select_related('ticket', 'user').order_by('-started_at')[:50]
    unbilled_expenses = TicketExpense.objects.filter(
        ticket__organization=client, is_billable=True,
    ).select_related('ticket', 'user').order_by('-incurred_on')[:50]

    return render(request, 'psa/client_account.html', {
        'client': client,
        'summary': summary,
        'invoices': invoices.select_related('client_org').order_by('-invoice_date')[:100],
        'charges': charges.order_by('-charge_date')[:100],
        'payments': payments.select_related('invoice').order_by('-paid_on')[:50],
        'unbilled_time': unbilled_time,
        'unbilled_expenses': unbilled_expenses,
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def charge_add(request, org_id):
    """Quick-add a one-off charge against a client's account."""
    from .models import Charge
    from core.models import Organization
    from datetime import date as _date
    org = get_request_organization(request)
    client = get_object_or_404(Organization, pk=org_id)

    description = (request.POST.get('description') or '').strip()
    if not description:
        messages.error(request, 'Description is required.')
        return redirect('psa:client_account', org_id=org_id)
    try:
        amount = float(request.POST.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        messages.error(request, 'Amount must be positive.')
        return redirect('psa:client_account', org_id=org_id)

    Charge.objects.create(
        organization=org or client,
        client_org=client,
        description=description[:300],
        amount=amount,
        currency=(request.POST.get('currency') or 'USD')[:8],
        charge_date=request.POST.get('charge_date') or _date.today(),
        is_credit=request.POST.get('is_credit') == 'on',
        is_recurring=request.POST.get('is_recurring') == 'on',
        recurrence=request.POST.get('recurrence') or 'once',
        notes=(request.POST.get('notes') or '').strip(),
        created_by=request.user,
    )
    AuditLog.log(
        user=request.user, action='create',
        organization=org or client,
        object_type='psa.Charge', object_id=0,
        object_repr=description,
        description=f'{"Credit" if request.POST.get("is_credit") == "on" else "Charge"} {amount:.2f} on {client.name}: {description}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Recorded {"credit" if request.POST.get("is_credit") == "on" else "charge"} of {amount:.2f}.')
    return redirect('psa:client_account', org_id=org_id)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def charge_invoice(request, org_id):
    """Roll all uninvoiced charges + credits for this client into a new
    draft invoice. Marks each charge invoiced=True with invoice FK set."""
    from .models import Charge, Invoice, InvoiceLineItem
    from core.models import Organization
    from datetime import date as _date
    org = get_request_organization(request)
    client = get_object_or_404(Organization, pk=org_id)
    qs = Charge.objects.filter(client_org=client, invoiced=False)
    if org is not None:
        qs = qs.filter(organization=org)
    if not qs.exists():
        messages.info(request, 'No uninvoiced charges or credits to bill.')
        return redirect('psa:client_account', org_id=org_id)

    invoice = Invoice.objects.create(
        organization=org or client,
        client_org=client,
        title=f'Account charges through {_date.today():%Y-%m-%d}',
        invoice_date=_date.today(),
        created_by=request.user,
    )
    for i, c in enumerate(qs.order_by('charge_date')):
        # Credits come through as negative-priced line items.
        sign = -1 if c.is_credit else 1
        InvoiceLineItem.objects.create(
            invoice=invoice, sort_order=i,
            description=c.description[:300],
            quantity=1,
            unit_price=sign * float(c.amount),
            source='manual',
            source_id=str(c.pk),
        )
    qs.update(invoiced=True, invoice=invoice)
    invoice.recompute_totals()
    messages.success(request, f'Bundled {qs.count()} item(s) into invoice {invoice.invoice_number}.')
    return redirect('psa:invoice_detail', pk=invoice.pk)


@login_required
@require_psa_enabled
def aging_report(request):
    """Cross-client aging report. Sums each client's outstanding balance
    bucketed by 0-30 / 31-60 / 61-90 / 90+ days past due_date."""
    from .models import Invoice, get_psa_balance
    from core.models import Organization
    org = get_request_organization(request)

    # Find every client that has at least one non-void invoice
    client_ids = Invoice.objects.exclude(status='void').values_list('client_org', flat=True)
    if org is not None:
        client_ids = Invoice.objects.filter(organization=org).exclude(status='void').values_list('client_org', flat=True)
    client_ids = list(set(client_ids))
    rows = []
    totals = {'outstanding': 0, '0_30': 0, '31_60': 0, '61_90': 0, '90_plus': 0,
              'credit_total': 0, 'net_balance': 0}
    for client in Organization.objects.filter(pk__in=client_ids).order_by('name'):
        s = get_psa_balance(client, msp_org=org)
        if s['outstanding'] == 0 and s['credit_total'] == 0:
            continue
        rows.append({'client': client, 'summary': s})
        totals['outstanding'] += float(s['outstanding'])
        totals['credit_total'] += float(s['credit_total'])
        totals['net_balance'] += float(s['net_balance'])
        for k in ('0_30', '31_60', '61_90', '90_plus'):
            totals[k] += float(s['aging'][k])

    return render(request, 'psa/aging_report.html', {
        'rows': rows,
        'totals': totals,
    })


# ---------------------------------------------------------------------------
# Apply a Process workflow to a native PSA ticket
# ---------------------------------------------------------------------------


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def ticket_launch_workflow(request, ticket_number):
    """
    Pick a process from the catalog (organization-scoped + global) and
    launch a ProcessExecution against this ticket. The execution gets
    `native_psa_ticket=ticket` so the relationship is queryable from
    either side.
    """
    from processes.models import Process, ProcessExecution
    from django.db.models import Q

    org = get_request_organization(request)
    qs = Ticket.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    ticket = get_object_or_404(qs, ticket_number=ticket_number)

    # Available processes — global + same-org as the ticket's client
    processes = Process.objects.filter(
        Q(is_global=True) | Q(organization=ticket.organization),
        is_active=True,
    ).order_by('name')

    if request.method == 'POST':
        try:
            process = processes.get(pk=request.POST.get('process') or 0)
        except (Process.DoesNotExist, ValueError):
            messages.error(request, 'Pick a valid workflow.')
            return redirect('psa:ticket_detail', ticket_number=ticket_number)

        execution = ProcessExecution.objects.create(
            process=process,
            organization=ticket.organization,
            assigned_to=request.user,
            started_by=request.user,
            started_at=timezone.now(),
            status='in_progress',
            native_psa_ticket=ticket,
            notes=(request.POST.get('notes') or '').strip()[:5000],
        )

        # Drop a system note on the ticket so timeline shows the launch
        TicketComment.objects.create(
            ticket=ticket, body=f'Launched workflow: **{process.name}** (execution #{execution.pk})',
            is_internal=True, is_system=True,
            source='workflow',
        )
        AuditLog.log(
            user=request.user, action='create',
            organization=ticket.organization,
            object_type='processes.ProcessExecution', object_id=execution.pk,
            object_repr=f'{process.name} on {ticket.ticket_number}',
            description=f'Launched workflow "{process.name}" against {ticket.ticket_number}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Launched "{process.name}".')
        try:
            return redirect('processes:execution_detail', pk=execution.pk)
        except Exception:
            return redirect('psa:ticket_detail', ticket_number=ticket_number)

    return render(request, 'psa/ticket_launch_workflow.html', {
        'ticket': ticket,
        'processes': processes,
    })


# ---------------------------------------------------------------------------
# Invite a client portal user — creates User + Membership + emails a set-password link
# ---------------------------------------------------------------------------


@login_required
@require_admin
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def portal_invite(request, org_id):
    """
    Send a portal invite to a client user. Creates a Django User (with
    an unusable password), a Membership in the client org, and emails
    a one-time tokenized set-password link.
    """
    from django.contrib.auth.models import User
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    from django.urls import reverse
    from django.core.mail import EmailMultiAlternatives
    from accounts.models import Membership, Role
    from core.models import Organization
    from psa.models import ClientPSASettings

    org = get_object_or_404(Organization, pk=org_id)

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()
        full_name = (request.POST.get('full_name') or '').strip()
        if not email or '@' not in email:
            messages.error(request, 'A valid email is required.')
            return redirect(request.path)

        # Ensure the org has portal_enabled — invite is meaningless otherwise.
        settings_row, _ = ClientPSASettings.objects.get_or_create(organization=org)
        if not settings_row.portal_enabled:
            settings_row.portal_enabled = True
            settings_row.save(update_fields=['portal_enabled', 'updated_at'])
            messages.info(request, f'Enabled the customer portal for {org.name}.')

        first, _, last = full_name.partition(' ')
        user, created = User.objects.get_or_create(
            email=email,
            defaults={'username': email[:150], 'first_name': first[:30],
                      'last_name': last[:150], 'is_active': True},
        )
        if created:
            user.set_unusable_password()
            user.save()
        # Force username sync if the User existed but had no email match
        if not user.username:
            user.username = email[:150]
            user.save(update_fields=['username'])

        is_org_admin = request.POST.get('is_org_admin') == 'on'
        Membership.objects.update_or_create(
            user=user, organization=org,
            defaults={'role': Role.READONLY, 'is_active': True,
                      'is_org_admin': is_org_admin,
                      'invited_by': request.user},
        )

        # Build one-time password-set link
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        path = reverse('accounts:portal_set_password',
                       kwargs={'uidb64': uid, 'token': token})
        link = request.build_absolute_uri(path)

        portal_url = request.build_absolute_uri('/portal/')
        subject = f'Your support portal account for {org.name}'
        text = (
            f'Hello{(" " + first) if first else ""},\n\n'
            f'You have been invited to access the support portal for {org.name}.\n\n'
            f'1. Click the link below to set your password:\n   {link}\n\n'
            f'2. After setting your password, sign in at:\n   {portal_url}\n\n'
            f'From there you can submit tickets, see updates from our support '
            f'team, and read knowledge-base articles we make available.\n\n'
            f'If you did not expect this invitation, you can safely ignore this email.\n'
        )
        try:
            msg = EmailMultiAlternatives(subject, text, to=[email])
            msg.send(fail_silently=False)
        except Exception as exc:
            messages.warning(request, f'User created but email send failed: {exc}. Invite link: {link}')
        else:
            messages.success(request, f'Invited {email} to the {org.name} portal.')

        AuditLog.log(
            user=request.user, action='create',
            organization=org,
            object_type='auth.User', object_id=user.pk,
            object_repr=f'portal user {email}',
            description=f'Invited {email} to {org.name} portal (membership=readonly)',
            ip_address=_client_ip(request), path=request.path,
        )
        return redirect('psa:client_account', org_id=org.pk)

    # GET — show the invite form
    return render(request, 'psa/portal_invite.html', {
        'org': org,
    })


# ---------------------------------------------------------------------------
# Dispatch board — drag-and-drop reassignment endpoint
# ---------------------------------------------------------------------------

@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def dispatch_assign(request):
    """
    JSON endpoint hit by the dispatch board's drag-and-drop handler.
    POST: ticket_number, assignee (user pk or 'unassigned').
    Defence-in-depth: re-checks the ticket is in scope for the user's
    current org filter.
    """
    from django.http import JsonResponse
    from django.contrib.auth.models import User
    org = get_request_organization(request)
    qs = Ticket.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    tn = (request.POST.get('ticket_number') or '').strip()
    assignee = (request.POST.get('assignee') or '').strip()
    if not tn:
        return JsonResponse({'error': 'ticket_number required'}, status=400)
    try:
        ticket = qs.get(ticket_number=tn)
    except Ticket.DoesNotExist:
        return JsonResponse({'error': 'ticket not found'}, status=404)
    # Admin-level assignment check — staff/superuser, or org admin/owner of
    # the TICKET's org (not just the requester's currently-selected org).
    if not _can_assign(request, ticket.organization):
        return JsonResponse({'error': 'forbidden'}, status=403)
    old_assignee = ticket.assigned_to
    if assignee in ('', 'unassigned'):
        ticket.assigned_to = None
    else:
        try:
            target = User.objects.get(pk=int(assignee), is_active=True)
        except (User.DoesNotExist, ValueError):
            return JsonResponse({'error': 'invalid assignee'}, status=400)
        # Target must be staff/superuser or a member of the ticket's org.
        eligible_ids = set(
            _eligible_assignees(ticket.organization).values_list('id', flat=True)
        )
        if target.id not in eligible_ids:
            return JsonResponse({'error': 'assignee not eligible for this org'}, status=400)
        ticket.assigned_to = target
    ticket.save(update_fields=['assigned_to', 'updated_at'])
    # Phase 11.2: PTO + calendar conflict warnings. Computed AFTER the
    # save so the new tech is the one being checked. We don't block —
    # the dispatcher made an explicit decision; the warnings surface as
    # advisory chips in the response.
    conflict_warnings = _dispatch_conflicts(ticket.assigned_to, ticket)
    AuditLog.log(
        user=request.user, action='update',
        organization=ticket.organization,
        object_type='psa.Ticket', object_id=ticket.pk,
        object_repr=ticket.ticket_number,
        description=(
            f'Dispatch DnD: {ticket.ticket_number} reassigned '
            f'from {old_assignee or "unassigned"} → {ticket.assigned_to or "unassigned"}'
            + (f' [conflicts: {"; ".join(conflict_warnings)}]'
               if conflict_warnings else '')
        ),
        ip_address=_client_ip(request), path=request.path,
    )
    return JsonResponse({
        'ok': True,
        'ticket_number': ticket.ticket_number,
        'assigned_to': ticket.assigned_to.username if ticket.assigned_to else '',
        'assigned_to_id': ticket.assigned_to_id or 0,
        'conflict_warnings': conflict_warnings,  # 11.2: empty list when no conflicts
    })


@login_required
@require_psa_enabled
def dispatch_heatmap(request):
    """
    Phase 11.3: per-tech / per-day load heatmap.

    Aggregates open tickets by (assigned_to, due_date) over a 14-day
    window — including 7 days back (already overdue or completed) and
    7 days forward. Cells render with color intensity proportional to
    ticket count so dispatchers can see distribution at a glance.

    Tenant scope: same as ``dispatch_board`` — current org only, all
    tickets when superuser/staff in global view.
    """
    from datetime import date, timedelta

    org = get_request_organization(request)
    qs = Ticket.objects.select_related('assigned_to', 'priority', 'status')
    if org is not None:
        qs = qs.filter(organization=org)

    today = date.today()
    days = [today + timedelta(days=i) for i in range(-7, 8)]  # ±7 days

    # Aggregate: counts[user_id][date] = ticket_count
    counts: dict[int, dict[date, int]] = {}
    techs: dict[int, object] = {}
    max_count = 0

    for t in qs.order_by('-created_at')[:2000]:
        if not t.assigned_to_id:
            continue
        due = t.resolution_due_at or t.first_response_due_at
        if not due:
            continue
        d_local = timezone.localtime(due).date() if hasattr(due, 'date') else due
        if d_local not in days:
            continue
        techs[t.assigned_to_id] = t.assigned_to
        bucket = counts.setdefault(t.assigned_to_id, {})
        bucket[d_local] = bucket.get(d_local, 0) + 1
        if bucket[d_local] > max_count:
            max_count = bucket[d_local]

    # Build rows: list of dicts with tech + per-day cells, sorted by username.
    rows = []
    for tech in sorted(techs.values(), key=lambda u: (u.username or '').lower()):
        bucket = counts.get(tech.id, {})
        cells = []
        for d in days:
            count = bucket.get(d, 0)
            # Intensity 0..4 — bucketize the count into one of 5 shade classes
            # the template renders as background-color CSS.
            if count == 0:
                intensity = 0
            elif max_count <= 1:
                intensity = 4 if count else 0
            else:
                intensity = min(4, 1 + int((count - 1) * 4 / max(1, max_count - 1)))
            cells.append({
                'date': d,
                'count': count,
                'intensity': intensity,
                'is_today': d == today,
                'is_past': d < today,
            })
        rows.append({'tech': tech, 'cells': cells})

    return render(request, 'psa/dispatch_heatmap.html', {
        'days': days,
        'rows': rows,
        'today': today,
        'max_count': max_count,
    })


# ---------------------------------------------------------------------------
# Procurement (Phase 4.1) — Purchase Requisitions + Purchase Orders
# ---------------------------------------------------------------------------

from accounts.permission_utils import require_perm, user_has_perm  # noqa: E402


def _procurement_save_lines(item, line_model, request):
    """Replace line_items on a PR/PO from POSTed lists, returning total."""
    descs = request.POST.getlist('li_description')
    skus = request.POST.getlist('li_sku')
    providers = request.POST.getlist('li_provider')
    qtys = request.POST.getlist('li_quantity')
    prices = request.POST.getlist('li_unit_price')
    if descs:
        item.line_items.all().delete()
        for i, d in enumerate(descs):
            if not (d or '').strip():
                continue
            try:
                qf = float(qtys[i] if i < len(qtys) and qtys[i] else 1)
                pf = float(prices[i] if i < len(prices) and prices[i] else 0)
            except (ValueError, IndexError):
                qf, pf = 1, 0
            kwargs = dict(
                sort_order=i,
                description=d.strip()[:300],
                sku=(skus[i] if i < len(skus) else '')[:80],
                distributor_provider=(providers[i] if i < len(providers) else '')[:40],
                quantity=qf, unit_price=pf,
            )
            if line_model.__name__ == 'PurchaseOrderLineItem':
                kwargs['po'] = item
            else:
                kwargs['requisition'] = item
            line_model.objects.create(**kwargs)


@login_required
@require_psa_enabled
@require_perm('procurement_view')
def requisition_list(request):
    from .models import PurchaseRequisition
    org = get_request_organization(request)
    qs = PurchaseRequisition.objects.select_related('client_org', 'requested_by', 'approver')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    status = request.GET.get('status')
    if status in {c[0] for c in PurchaseRequisition.STATUS_CHOICES}:
        qs = qs.filter(status=status)

    # Mine vs. everyone — non-approvers see only their own PRs by default.
    can_approve = user_has_perm(request.user, 'procurement_approve_pr')
    mine_param = request.GET.get('mine')
    if can_approve:
        # Approvers see all by default; ?mine=1 narrows to their own.
        view_mine = mine_param == '1'
    else:
        # Techs without approve perm see only their PRs (always).
        view_mine = True
    if view_mine:
        qs = qs.filter(requested_by=request.user)

    return render(request, 'psa/requisition_list.html', {
        'requisitions': qs.order_by('-requested_at')[:200],
        'status_filter': status or '',
        'view_mine': view_mine,
        'can_approve': can_approve,
    })


@login_required
@require_psa_enabled
@require_perm('procurement_view')
def requisition_detail(request, pk):
    from .models import PurchaseRequisition
    from accounts.permission_utils import user_has_perm
    org = get_request_organization(request)
    qs = PurchaseRequisition.objects.select_related(
        'client_org', 'organization', 'requested_by', 'approver',
        'source_ticket', 'source_project',
    )
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    return render(request, 'psa/requisition_detail.html', {
        'item': item,
        'line_items': item.line_items.all(),
        'can_approve': user_has_perm(request.user, 'procurement_approve_pr'),
        'can_create_po': user_has_perm(request.user, 'procurement_create_po'),
    })


@login_required
@require_psa_enabled
@require_perm('procurement_create_pr')
@require_http_methods(['GET', 'POST'])
def requisition_form(request, pk=None):
    from .models import PurchaseRequisition, PurchaseRequisitionLineItem
    from core.models import Organization
    if pk:
        item = get_object_or_404(PurchaseRequisition, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    def _render():
        return render(request, 'psa/requisition_form.html', {
            'item': item,
            'client_orgs': client_orgs,
            'status_choices': PurchaseRequisition.STATUS_CHOICES,
            'line_items': item.line_items.all() if item else [],
            'selected_org_id': item.organization_id if item else (org.pk if org else None),
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('organization_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid organization.')
                return _render()
        else:
            item_org = org

        if item_org is None:
            messages.error(request, 'Please choose an MSP organization for this requisition.')
            return _render()

        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
            return _render()

        client_org = None
        client_org_id = (request.POST.get('client_org') or '').strip()
        if client_org_id:
            try:
                client_org = Organization.objects.get(pk=int(client_org_id))
            except (Organization.DoesNotExist, ValueError, TypeError):
                client_org = None

        if item is None:
            item = PurchaseRequisition(
                organization=item_org,
                title=title,
                requested_by=request.user,
            )
        item.organization = item_org
        item.client_org = client_org
        item.title = title
        item.description = (request.POST.get('description') or '').strip()
        item.notes = (request.POST.get('notes') or '').strip()
        # status only changeable if approve/reject — drafts stay draft from form
        if not pk:
            item.status = 'draft'
        try:
            item.tax_rate = request.POST.get('tax_rate') or 0
        except (TypeError, ValueError):
            item.tax_rate = 0
        item.currency = (request.POST.get('currency') or 'USD')[:8]
        item.save()

        _procurement_save_lines(item, PurchaseRequisitionLineItem, request)
        item.recompute_totals()
        item.save(update_fields=['subtotal', 'tax_amount', 'total', 'updated_at'])

        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=item_org,
            object_type='psa.PurchaseRequisition', object_id=item.pk,
            object_repr=item.pr_number,
            description=f'{"Updated" if pk else "Created"} requisition {item.pr_number}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Saved {item.pr_number}.')
        return redirect('psa:requisition_detail', pk=item.pk)

    return _render()


@login_required
@require_psa_enabled
@require_perm('procurement_create_pr')
@require_http_methods(['POST'])
def requisition_submit(request, pk):
    from .models import PurchaseRequisition
    org = get_request_organization(request)
    qs = PurchaseRequisition.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    if item.status != 'draft':
        messages.error(request, f'Cannot submit — already {item.get_status_display()}.')
        return redirect('psa:requisition_detail', pk=item.pk)
    item.status = 'submitted'
    item.save(update_fields=['status', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=item.organization,
        object_type='psa.PurchaseRequisition', object_id=item.pk,
        object_repr=item.pr_number,
        description=f'Submitted requisition {item.pr_number} for approval',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Requisition {item.pr_number} submitted for approval.')
    return redirect('psa:requisition_detail', pk=item.pk)


@login_required
@require_psa_enabled
@require_perm('procurement_approve_pr')
@require_http_methods(['POST'])
def requisition_decide(request, pk):
    from .models import PurchaseRequisition
    org = get_request_organization(request)
    qs = PurchaseRequisition.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    if item.status != 'submitted':
        messages.error(request, f'Cannot decide — requisition is {item.get_status_display()}.')
        return redirect('psa:requisition_detail', pk=item.pk)

    decision = (request.POST.get('decision') or '').strip()
    note = (request.POST.get('decision_note') or '').strip()
    if decision == 'approve':
        item.status = 'approved'
    elif decision == 'reject':
        item.status = 'rejected'
    else:
        messages.error(request, 'Decision must be approve or reject.')
        return redirect('psa:requisition_detail', pk=item.pk)

    item.approver = request.user
    item.decided_at = timezone.now()
    item.decision_note = note
    item.save(update_fields=['status', 'approver', 'decided_at',
                             'decision_note', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=item.organization,
        object_type='psa.PurchaseRequisition', object_id=item.pk,
        object_repr=item.pr_number,
        description=f'{decision.capitalize()}d requisition {item.pr_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Requisition {item.pr_number} {item.get_status_display().lower()}.')
    return redirect('psa:requisition_detail', pk=item.pk)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def requisition_to_po(request, pk):
    """Convert an approved PR into a draft PO with the same line items.

    Either approve-PR or create-PO permission is sufficient — managers who
    approve the PR are usually the same people kicking off the PO step.
    """
    if not (
        user_has_perm(request.user, 'procurement_approve_pr')
        or user_has_perm(request.user, 'procurement_create_po')
    ):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(
            "You don't have the 'procurement_approve_pr' or 'procurement_create_po' permission."
        )
    from .models import (
        PurchaseRequisition, PurchaseOrder, PurchaseOrderLineItem,
    )
    org = get_request_organization(request)
    qs = PurchaseRequisition.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    pr = get_object_or_404(qs, pk=pk)
    if pr.status != 'approved':
        messages.error(request, f'Cannot convert — requisition is {pr.get_status_display()}.')
        return redirect('psa:requisition_detail', pk=pr.pk)

    vendor_name = (request.POST.get('vendor_name') or '').strip() or 'Vendor TBD'
    vendor_email = (request.POST.get('vendor_email') or '').strip()

    po = PurchaseOrder.objects.create(
        organization=pr.organization,
        client_org=pr.client_org,
        requisition=pr,
        vendor_name=vendor_name[:200],
        vendor_email=vendor_email[:254],
        title=pr.title[:200],
        notes=pr.notes,
        tax_rate=pr.tax_rate,
        currency=pr.currency,
        created_by=request.user,
    )
    for li in pr.line_items.all():
        PurchaseOrderLineItem.objects.create(
            po=po,
            description=li.description,
            sku=li.sku,
            distributor_provider=li.distributor_provider,
            quantity=li.quantity,
            unit_price=li.unit_price,
            sort_order=li.sort_order,
        )
    po.recompute_totals()
    po.save(update_fields=['subtotal', 'tax_amount', 'total', 'updated_at'])

    pr.status = 'converted'
    pr.save(update_fields=['status', 'updated_at'])

    AuditLog.log(
        user=request.user, action='create',
        organization=po.organization,
        object_type='psa.PurchaseOrder', object_id=po.pk,
        object_repr=po.po_number,
        description=f'Converted {pr.pr_number} to PO {po.po_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Created {po.po_number} from {pr.pr_number}.')
    return redirect('psa:po_detail', pk=po.pk)


# --- Purchase Orders ---


@login_required
@require_psa_enabled
@require_perm('procurement_view')
def po_list(request):
    from .models import PurchaseOrder
    org = get_request_organization(request)
    qs = PurchaseOrder.objects.select_related('client_org', 'created_by')
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    status = request.GET.get('status')
    if status in {c[0] for c in PurchaseOrder.STATUS_CHOICES}:
        qs = qs.filter(status=status)
    return render(request, 'psa/po_list.html', {
        'pos': qs.order_by('-created_at')[:200],
        'status_filter': status or '',
    })


@login_required
@require_psa_enabled
@require_perm('procurement_view')
def po_detail(request, pk):
    from .models import PurchaseOrder
    from accounts.permission_utils import user_has_perm
    org = get_request_organization(request)
    qs = PurchaseOrder.objects.select_related(
        'client_org', 'organization', 'requisition', 'created_by',
    )
    if org is not None:
        qs = qs.filter(organization=org)
    item = get_object_or_404(qs, pk=pk)
    return render(request, 'psa/po_detail.html', {
        'item': item,
        'line_items': item.line_items.all(),
        'receipts': item.receipts.all().select_related('received_by').prefetch_related('lines__po_line'),
        'open_back_orders': item.back_orders.filter(status='open').select_related('po_line'),
        'can_edit_po': user_has_perm(request.user, 'procurement_create_po'),
        'can_send_po': user_has_perm(request.user, 'procurement_send_po'),
        'can_receive': user_has_perm(request.user, 'procurement_view'),
    })


@login_required
@require_psa_enabled
@require_perm('procurement_create_po')
@require_http_methods(['GET', 'POST'])
def po_form(request, pk=None):
    from .models import PurchaseOrder, PurchaseOrderLineItem
    from core.models import Organization
    if pk:
        item = get_object_or_404(PurchaseOrder, pk=pk)
        org = item.organization
    else:
        item = None
        org = get_request_organization(request)

    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    # Phase 4.3: list of selectable vendors for the FK dropdown
    from assets.models import Vendor as ProcurementVendor
    vendor_choices = ProcurementVendor.objects.filter(is_active=True).order_by('name')

    def _render():
        return render(request, 'psa/po_form.html', {
            'item': item,
            'client_orgs': client_orgs,
            'status_choices': PurchaseOrder.STATUS_CHOICES,
            'line_items': item.line_items.all() if item else [],
            'selected_org_id': item.organization_id if item else (org.pk if org else None),
            'vendor_choices': vendor_choices,
        })

    if request.method == 'POST':
        posted_org_id = (request.POST.get('organization_id') or '').strip()
        if posted_org_id:
            try:
                item_org = Organization.objects.get(pk=int(posted_org_id), is_active=True)
            except (Organization.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Invalid organization.')
                return _render()
        else:
            item_org = org
        if item_org is None:
            messages.error(request, 'Please choose an MSP organization for this PO.')
            return _render()

        # Phase 4.3 — vendor FK lookup (optional). If set, snapshot fields
        # auto-fill from the vendor row when the corresponding form field
        # is blank.
        vendor_obj = None
        vendor_id = (request.POST.get('vendor') or '').strip()
        if vendor_id:
            try:
                vendor_obj = ProcurementVendor.objects.get(pk=int(vendor_id))
            except (ProcurementVendor.DoesNotExist, ValueError, TypeError):
                vendor_obj = None

        title = (request.POST.get('title') or '').strip()
        vendor_name = (request.POST.get('vendor_name') or '').strip()
        # If user picked a vendor and didn't type a name, fall back to vendor.name
        if not vendor_name and vendor_obj:
            vendor_name = vendor_obj.name
        if not title or not vendor_name:
            messages.error(request, 'Title and vendor name are required.')
            return _render()

        client_org = None
        client_org_id = (request.POST.get('client_org') or '').strip()
        if client_org_id:
            try:
                client_org = Organization.objects.get(pk=int(client_org_id))
            except (Organization.DoesNotExist, ValueError, TypeError):
                client_org = None

        if item is None:
            item = PurchaseOrder(
                organization=item_org,
                created_by=request.user,
            )
        item.organization = item_org
        item.client_org = client_org
        item.vendor = vendor_obj
        item.title = title[:200]
        item.vendor_name = vendor_name[:200]
        # Auto-fill snapshot fields from the vendor when the form field is blank
        posted_vendor_email = (request.POST.get('vendor_email') or '').strip()
        posted_vendor_phone = (request.POST.get('vendor_phone') or '').strip()
        posted_vendor_address = (request.POST.get('vendor_address') or '').strip()
        if vendor_obj:
            posted_vendor_email = posted_vendor_email or (vendor_obj.contact_email or '')
            posted_vendor_phone = posted_vendor_phone or (vendor_obj.contact_phone or '')
            posted_vendor_address = posted_vendor_address or (vendor_obj.billing_address or '')
        item.vendor_email = posted_vendor_email[:254]
        item.vendor_phone = posted_vendor_phone[:40]
        item.vendor_address = posted_vendor_address
        item.notes = (request.POST.get('notes') or '').strip()
        item.status = request.POST.get('status') or 'draft'
        item.issue_date = request.POST.get('issue_date') or None
        # Auto-fill expected delivery from issue_date + vendor lead time when
        # blank and a vendor is set.
        expected = request.POST.get('expected_delivery_date') or None
        if not expected and vendor_obj and item.issue_date:
            from datetime import timedelta as _td
            try:
                expected = (item.issue_date + _td(days=vendor_obj.default_lead_time_days)).isoformat() \
                    if hasattr(item.issue_date, 'isoformat') else None
            except Exception:
                expected = None
        elif not expected and vendor_obj:
            from datetime import date as _d, timedelta as _td
            expected = (_d.today() + _td(days=vendor_obj.default_lead_time_days)).isoformat()
        item.expected_delivery_date = expected or None
        item.is_drop_ship = request.POST.get('is_drop_ship') == 'on'
        item.ship_to_name = (request.POST.get('ship_to_name') or '').strip()[:200]
        item.ship_to_address = (request.POST.get('ship_to_address') or '').strip()
        try:
            item.tax_rate = request.POST.get('tax_rate') or 0
        except (TypeError, ValueError):
            item.tax_rate = 0
        try:
            item.shipping_cost = request.POST.get('shipping_cost') or 0
        except (TypeError, ValueError):
            item.shipping_cost = 0
        item.currency = (request.POST.get('currency') or 'USD')[:8]
        item.save()

        _procurement_save_lines(item, PurchaseOrderLineItem, request)
        item.recompute_totals()
        item.save(update_fields=['subtotal', 'tax_amount', 'total', 'updated_at'])

        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=item_org,
            object_type='psa.PurchaseOrder', object_id=item.pk,
            object_repr=item.po_number,
            description=f'{"Updated" if pk else "Created"} purchase order {item.po_number}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Saved {item.po_number}.')
        return redirect('psa:po_detail', pk=item.pk)

    return _render()


@login_required
@require_psa_enabled
@require_perm('procurement_view')
def po_pdf(request, pk):
    from django.http import HttpResponse
    from .po_pdf import render_po_pdf
    from .models import PurchaseOrder
    org = get_request_organization(request)
    qs = PurchaseOrder.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    po = get_object_or_404(
        qs.select_related('client_org', 'organization'), pk=pk,
    )
    pdf_bytes = render_po_pdf(po)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') else 'inline'
    resp['Content-Disposition'] = f'{disposition}; filename="{po.po_number}.pdf"'
    return resp


@login_required
@require_psa_enabled
@require_perm('procurement_send_po')
@require_http_methods(['POST'])
def po_send(request, pk):
    from .po_pdf import email_po
    from .models import PurchaseOrder
    org = get_request_organization(request)
    qs = PurchaseOrder.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    po = get_object_or_404(qs.select_related('client_org', 'organization'), pk=pk)
    recipient = (request.POST.get('recipient') or po.vendor_email or '').strip()
    subject = (request.POST.get('subject') or '').strip()
    body = (request.POST.get('body') or '').strip()
    if not recipient or '@' not in recipient:
        messages.error(request, 'Provide a valid vendor recipient email.')
        return redirect('psa:po_detail', pk=po.pk)
    try:
        ok = email_po(po, recipient=recipient, subject=subject, body=body)
    except Exception as exc:
        messages.error(request, f'Email failed: {exc}')
        return redirect('psa:po_detail', pk=po.pk)
    if ok:
        if po.status == 'draft':
            po.status = 'sent'
            po.sent_at = timezone.now()
            po.save(update_fields=['status', 'sent_at', 'updated_at'])
        AuditLog.log(
            user=request.user, action='update',
            organization=po.organization,
            object_type='psa.PurchaseOrder', object_id=po.pk,
            object_repr=po.po_number,
            description=f'Emailed PO {po.po_number} to {recipient}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Sent PO {po.po_number} to {recipient}.')
    else:
        messages.error(request, 'Email send returned 0 recipients.')
    return redirect('psa:po_detail', pk=po.pk)


# ---------------------------------------------------------------------------
# Procurement (Phase 4.2) — Receiving + back-orders + serial-number capture
# ---------------------------------------------------------------------------

def _recompute_po_status(po):
    """Set PO status to draft / partial / received based on line aggregates."""
    if po.status in ('cancelled', 'void', 'draft'):
        return
    total_qty = sum((l.quantity or 0) for l in po.line_items.all())
    received_qty = sum((l.received_quantity or 0) for l in po.line_items.all())
    if total_qty == 0:
        return
    if received_qty == 0:
        # Don't downgrade from sent/acknowledged
        return
    if received_qty < total_qty:
        po.status = 'partial'
    else:
        po.status = 'received'
        # Close any open back-orders
        po.back_orders.filter(status='open').update(
            status='filled', closed_at=timezone.now(),
        )
    po.save(update_fields=['status'])


def _maybe_create_assets_from_serials(line, serials, receipt, user):
    """When serial numbers are captured, optionally create assets.Asset rows
    so the inventory chain is complete. Skips silently if assets app or
    Asset model has incompatible signature."""
    if not serials:
        return
    try:
        from assets.models import Asset
    except Exception:
        return
    org = line.po.client_org or line.po.organization
    for sn in serials:
        # Skip duplicates
        if Asset.objects.filter(serial_number=sn).exists():
            continue
        try:
            Asset.objects.create(
                organization=org,
                name=f'{line.description} ({sn})'[:200],
                serial_number=sn,
                notes=f'Auto-created from PO {line.po.po_number} receipt #{receipt.pk}',
                # status default; let model defaults handle the rest
            )
        except Exception:
            # Some Asset models require asset_type or other FKs we can't infer.
            # In that case we just skip — the receipt + serial captures still
            # land in POReceiptLine.serial_numbers as the audit trail.
            continue


@login_required
@require_psa_enabled
@require_perm('procurement_view')
@require_http_methods(['GET', 'POST'])
def po_receive(request, pk):
    """
    GET: render receiving form for an open PO (one row per line item with
    a 'qty received' input, optional serial-numbers comma-separated
    textarea, carrier + tracking inputs).
    POST: create POReceipt + POReceiptLine rows, roll up
    PurchaseOrderLineItem.received_quantity, recompute PO status,
    create POBackOrder rows for shorted lines, optionally create
    assets.Asset rows from captured serial numbers, audit-log.
    """
    from .models import (
        PurchaseOrder, POReceipt, POReceiptLine, POBackOrder,
    )
    org = get_request_organization(request)
    qs = PurchaseOrder.objects.select_related('client_org', 'organization')
    if org is not None:
        qs = qs.filter(organization=org)
    po = get_object_or_404(qs, pk=pk)

    if request.method == 'POST':
        from decimal import Decimal
        from django.db import transaction

        carrier = (request.POST.get('carrier') or '').strip()[:80]
        tracking = (request.POST.get('tracking_number') or '').strip()[:120]
        notes = (request.POST.get('notes') or '').strip()
        is_drop_ship_confirmed = (request.POST.get('is_drop_ship_confirmed') == 'on')

        with transaction.atomic():
            receipt = POReceipt.objects.create(
                po=po, received_by=request.user,
                carrier=carrier, tracking_number=tracking,
                notes=notes, is_drop_ship_confirmed=is_drop_ship_confirmed,
            )
            for line in po.line_items.all():
                qty_str = (request.POST.get(f'qty_line_{line.pk}') or '').strip()
                if not qty_str:
                    continue
                try:
                    qty = Decimal(qty_str)
                except Exception:
                    continue
                if qty <= 0:
                    continue
                # Cap qty at remaining
                remaining = (line.quantity or Decimal('0')) - (line.received_quantity or Decimal('0'))
                if qty > remaining:
                    qty = remaining
                if qty <= 0:
                    continue

                serials_raw = (request.POST.get(f'serials_line_{line.pk}') or '').strip()
                serials = [s.strip() for s in serials_raw.replace('\n', ',').split(',') if s.strip()]

                POReceiptLine.objects.create(
                    receipt=receipt, po_line=line,
                    quantity_received=qty, serial_numbers=serials,
                )
                # Roll up cumulative
                line.received_quantity = (line.received_quantity or Decimal('0')) + qty
                line.save(update_fields=['received_quantity'])

                # Optional: auto-create Asset rows from serials
                _maybe_create_assets_from_serials(line, serials, receipt, request.user)

                # Back-order if still short
                still_short = (line.quantity or Decimal('0')) - (line.received_quantity or Decimal('0'))
                if still_short > 0:
                    POBackOrder.objects.create(
                        po=po, po_line=line, quantity_outstanding=still_short,
                    )

            # Recompute PO status
            _recompute_po_status(po)

            # If a full receipt occurred against any line that had a prior
            # open back-order, fill it.
            for line in po.line_items.all():
                remaining = (line.quantity or Decimal('0')) - (line.received_quantity or Decimal('0'))
                if remaining <= 0:
                    line.back_orders.filter(status='open').update(
                        status='filled', closed_at=timezone.now(),
                    )

            # Audit log
            try:
                AuditLog.log(
                    user=request.user, action='update',
                    organization=po.organization,
                    object_type='psa.PurchaseOrder',
                    object_id=po.pk,
                    object_repr=po.po_number,
                    description=f'Received against {po.po_number} (receipt #{receipt.pk})',
                    ip_address=_client_ip(request), path=request.path,
                )
            except Exception:
                pass

        messages.success(request, f'Receipt #{receipt.pk} recorded.')
        return redirect('psa:po_detail', pk=po.pk)

    return render(request, 'psa/po_receive_form.html', {
        'po': po,
        'line_items': po.line_items.all(),
        'prior_receipts': po.receipts.all().select_related('received_by').prefetch_related('lines__po_line'),
    })


@login_required
@require_psa_enabled
@require_perm('procurement_view')
def back_order_list(request):
    from .models import POBackOrder
    org = get_request_organization(request)
    status = (request.GET.get('status') or 'open').strip()
    qs = POBackOrder.objects.select_related('po', 'po_line', 'po__client_org', 'po__organization')
    if org is not None:
        qs = qs.filter(po__organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    if status != 'all':
        qs = qs.filter(status=status)
    from accounts.permission_utils import user_has_perm
    return render(request, 'psa/back_order_list.html', {
        'back_orders': qs.order_by('-created_at')[:300],
        'status_filter': status,
        'can_cancel': user_has_perm(request.user, 'procurement_create_po'),
    })


@login_required
@require_psa_enabled
@require_perm('procurement_create_po')
@require_http_methods(['POST'])
def back_order_cancel(request, pk):
    from .models import POBackOrder
    org = get_request_organization(request)
    qs = POBackOrder.objects.select_related('po')
    if org is not None:
        qs = qs.filter(po__organization=org)
    bo = get_object_or_404(qs, pk=pk)
    if bo.status == 'open':
        bo.status = 'cancelled'
        bo.closed_at = timezone.now()
        bo.save(update_fields=['status', 'closed_at'])
        try:
            AuditLog.log(
                user=request.user, action='update',
                organization=bo.po.organization,
                object_type='psa.POBackOrder', object_id=bo.pk,
                object_repr=str(bo),
                description=f'Cancelled back-order on {bo.po.po_number}',
                ip_address=_client_ip(request), path=request.path,
            )
        except Exception:
            pass
        messages.success(request, 'Back-order cancelled.')
    else:
        messages.info(request, 'Back-order is not open; nothing changed.')
    return redirect('psa:back_order_list')


# ---------------------------------------------------------------------------
# Phase 4.3 — Vendor CRUD (procurement metadata on assets.Vendor)
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
@require_perm('procurement_view')
def vendor_list(request):
    """List all procurement vendors with key metadata + open POs counts."""
    from assets.models import Vendor
    from .models import PurchaseOrder
    from datetime import timedelta as _td
    from django.db.models import Count, Sum, Q
    from accounts.permission_utils import user_has_perm

    cutoff = timezone.now() - _td(days=30)
    open_statuses = ['draft', 'sent', 'acknowledged', 'partial']
    vendors = Vendor.objects.annotate(
        open_pos_count=Count(
            'purchase_orders',
            filter=Q(purchase_orders__status__in=open_statuses),
        ),
        spend_30d=Sum(
            'purchase_orders__total',
            filter=Q(purchase_orders__created_at__gte=cutoff),
        ),
    ).order_by('name')

    show_inactive = (request.GET.get('show_inactive') or '0') == '1'
    if not show_inactive:
        vendors = vendors.filter(is_active=True)

    return render(request, 'psa/vendor_list.html', {
        'vendors': vendors,
        'show_inactive': show_inactive,
        'can_edit': user_has_perm(request.user, 'procurement_create_po'),
    })


@login_required
@require_psa_enabled
@require_perm('procurement_view')
def vendor_detail(request, pk):
    """Vendor detail: metadata header, open POs, recent POs, 90d spend."""
    from assets.models import Vendor
    from .models import PurchaseOrder
    from datetime import timedelta as _td
    from decimal import Decimal as _Dec
    from django.db.models import Sum
    from accounts.permission_utils import user_has_perm

    vendor = get_object_or_404(Vendor, pk=pk)

    pos = PurchaseOrder.objects.filter(vendor=vendor)
    open_statuses = ['draft', 'sent', 'acknowledged', 'partial']
    closed_statuses = ['received', 'cancelled', 'void']

    open_pos = pos.filter(status__in=open_statuses).select_related(
        'client_org', 'organization').order_by('-created_at')
    recent_pos = pos.filter(status__in=closed_statuses).select_related(
        'client_org', 'organization').order_by('-created_at')[:10]

    cutoff = timezone.now() - _td(days=90)
    spend_90d = pos.filter(created_at__gte=cutoff).aggregate(
        total=Sum('total'))['total'] or _Dec('0')

    return render(request, 'psa/vendor_detail.html', {
        'vendor': vendor,
        'open_pos': open_pos,
        'recent_pos': recent_pos,
        'spend_90d': spend_90d,
        'can_edit': user_has_perm(request.user, 'procurement_create_po'),
    })


@login_required
@require_psa_enabled
@require_perm('procurement_create_po')
@require_http_methods(['GET', 'POST'])
def vendor_form(request, pk=None):
    """Create or edit a procurement vendor."""
    from assets.models import Vendor
    from django.utils.text import slugify

    vendor = get_object_or_404(Vendor, pk=pk) if pk else None

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        if not name:
            messages.error(request, 'Vendor name is required.')
            return render(request, 'psa/vendor_form.html', {
                'vendor': vendor,
                'payment_terms_choices': Vendor.PAYMENT_TERMS_CHOICES,
                'contact_method_choices': Vendor.CONTACT_METHOD_CHOICES,
            })

        if vendor is None:
            base = slugify(name) or 'vendor'
            slug = base
            i = 2
            while Vendor.objects.filter(slug=slug).exists():
                slug = f'{base}-{i}'
                i += 1
            vendor = Vendor(name=name, slug=slug)
        else:
            vendor.name = name[:200]

        # Basic fields
        vendor.website = (request.POST.get('website') or '').strip()[:200]
        vendor.support_url = (request.POST.get('support_url') or '').strip()[:200]
        vendor.support_phone = (request.POST.get('support_phone') or '').strip()[:50]
        vendor.description = (request.POST.get('description') or '').strip()
        vendor.is_active = (request.POST.get('is_active') == 'on')

        # Procurement metadata
        try:
            lt = int(request.POST.get('default_lead_time_days') or 7)
            vendor.default_lead_time_days = max(0, min(lt, 365))
        except (TypeError, ValueError):
            vendor.default_lead_time_days = 7
        valid_terms = {c[0] for c in Vendor.PAYMENT_TERMS_CHOICES}
        terms = (request.POST.get('payment_terms') or '').strip()
        vendor.payment_terms = terms if terms in valid_terms else ''
        valid_methods = {c[0] for c in Vendor.CONTACT_METHOD_CHOICES}
        method = (request.POST.get('preferred_contact_method') or '').strip()
        vendor.preferred_contact_method = method if method in valid_methods else ''
        vendor.contact_email = (request.POST.get('contact_email') or '').strip()[:254]
        vendor.contact_phone = (request.POST.get('contact_phone') or '').strip()[:40]
        vendor.billing_address = (request.POST.get('billing_address') or '').strip()
        vendor.account_number = (request.POST.get('account_number') or '').strip()[:80]
        vendor.notes = (request.POST.get('notes') or '').strip()
        vendor.distributor_provider = (request.POST.get('distributor_provider') or '').strip()[:40]

        vendor.save()

        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=None,
            object_type='assets.Vendor', object_id=vendor.pk,
            object_repr=vendor.name,
            description=f'{"Updated" if pk else "Created"} vendor {vendor.name}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Saved vendor "{vendor.name}".')
        return redirect('psa:vendor_detail', pk=vendor.pk)

    return render(request, 'psa/vendor_form.html', {
        'vendor': vendor,
        'payment_terms_choices': Vendor.PAYMENT_TERMS_CHOICES,
        'contact_method_choices': Vendor.CONTACT_METHOD_CHOICES,
    })


# ---------------------------------------------------------------------------
# Phase 4.4 — One-click PO from accepted quote
# ---------------------------------------------------------------------------


@login_required
@require_psa_enabled
@require_perm('procurement_create_po')
def quote_to_po(request, pk):
    """
    POST: create a draft PurchaseOrder from an accepted Quote.
    Copies line items, sets status='draft', links via po.source_quote
    (and an audit-crumb in po.notes back to the source quote).

    Optional vendor preselection via POST/GET ``vendor_id`` / ``vendor``.
    """
    from .models import Quote, PurchaseOrder, PurchaseOrderLineItem

    org = get_request_organization(request)
    qs = Quote.objects.select_related('client_org', 'organization')
    if org is not None:
        qs = qs.filter(organization=org)
    quote = get_object_or_404(qs, pk=pk)

    if quote.status != 'accepted':
        messages.error(request, 'Only accepted quotes can be converted to a PO.')
        return redirect('psa:quote_detail', pk=quote.pk)

    if request.method != 'POST':
        # Optional GET-style preview / confirm; redirect for safety.
        return redirect('psa:quote_detail', pk=quote.pk)

    # Optional vendor pre-fill
    vendor = None
    vendor_id = request.POST.get('vendor_id') or request.GET.get('vendor') or ''
    if vendor_id:
        try:
            from assets.models import Vendor
            vendor = Vendor.objects.filter(pk=int(vendor_id)).first()
        except (ValueError, TypeError):
            vendor = None

    po = PurchaseOrder(
        organization=quote.organization,
        client_org=quote.client_org,
        source_quote=quote,
        title=f'PO from quote {quote.quote_number}'[:200],
        status='draft',
        vendor=vendor,
        vendor_name=(vendor.name if vendor else '')[:200] or 'Vendor TBD',
        vendor_email=(getattr(vendor, 'contact_email', '') or '')[:254],
        vendor_phone=(getattr(vendor, 'contact_phone', '') or '')[:40],
        vendor_address=getattr(vendor, 'billing_address', '') or '',
        currency=getattr(quote, 'currency', 'USD') or 'USD',
        tax_rate=getattr(quote, 'tax_rate', 0) or 0,
        notes=f'Auto-created from accepted quote {quote.quote_number}.',
        created_by=request.user,
    )
    if vendor and getattr(vendor, 'default_lead_time_days', 0):
        from datetime import timedelta, date as _date
        po.expected_delivery_date = _date.today() + timedelta(days=vendor.default_lead_time_days)
    po.save()  # PO number auto-assigned via save() override

    # Copy line items — QuoteLineItem has description / quantity /
    # unit_price / sort_order (no sku / distributor on quote lines).
    for i, ql in enumerate(quote.line_items.all()):
        PurchaseOrderLineItem.objects.create(
            po=po,
            description=ql.description or '',
            sku=getattr(ql, 'sku', '') or '',
            distributor_provider=getattr(ql, 'distributor_provider', '') or '',
            quantity=ql.quantity or 0,
            unit_price=ql.unit_price or 0,
            sort_order=i,
        )

    po.recompute_totals()
    po.save(update_fields=['subtotal', 'tax_amount', 'total', 'updated_at'])

    # Audit-log the conversion
    try:
        AuditLog.log(
            user=request.user, action='create',
            organization=po.organization,
            object_type='psa.PurchaseOrder',
            object_id=po.pk,
            object_repr=po.po_number,
            description=f'Created PO {po.po_number} from quote {quote.quote_number}',
            ip_address=_client_ip(request), path=request.path,
        )
    except Exception:
        pass

    messages.success(
        request,
        f'PO {po.po_number} drafted from quote {quote.quote_number}. '
        f'Pick a vendor and review before sending.',
    )
    return redirect('psa:po_edit', pk=po.pk)


# ---------------------------------------------------------------------------
# Phase 6.1 — Change requests with CAB approval workflow
# ---------------------------------------------------------------------------


def _scoped_change_request_qs(request):
    """Tenant-scoped ChangeRequest queryset following the same staff/org
    pattern as `_scoped_ticket_qs`."""
    from .models import ChangeRequest
    qs = ChangeRequest.objects.select_related(
        'organization', 'ticket', 'ticket__ticket_type', 'ticket__status',
        'submitted_by', 'decided_by',
    )
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        return qs
    if hasattr(request.user, 'memberships'):
        org_ids = list(
            request.user.memberships.filter(is_active=True)
            .values_list('organization_id', flat=True)
        )
        return qs.filter(organization_id__in=org_ids)
    return qs.none()


def _get_change_for_ticket(request, ticket_number):
    """Resolve a ChangeRequest by ticket number with tenant scoping. Auto-
    creates the CR if the ticket is type='change' but no CR exists yet
    (covers tickets created before the signal was wired up)."""
    from .models import ChangeRequest
    qs = _scoped_ticket_qs(request).filter(ticket_number=ticket_number)
    ticket = get_object_or_404(qs)
    if not ticket.ticket_type or ticket.ticket_type.slug != 'change':
        raise Http404('Ticket is not a change request')
    cr, _ = ChangeRequest.objects.get_or_create(
        ticket=ticket,
        defaults={'organization': ticket.organization},
    )
    return ticket, cr


@login_required
@require_psa_enabled
def change_request_list(request):
    """Staff queue of change requests, filterable by risk + status."""
    from accounts.permission_utils import user_has_perm
    if not user_has_perm(request.user, 'change_view'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You don't have the 'change_view' permission.")
    from .models import ChangeRequest
    qs = _scoped_change_request_qs(request)
    risk = request.GET.get('risk') or ''
    status = request.GET.get('status') or ''
    if risk in {'low', 'medium', 'high', 'emergency'}:
        qs = qs.filter(risk=risk)
    valid_status = {s for s, _ in ChangeRequest.IMPLEMENTATION_STATUS}
    if status in valid_status:
        qs = qs.filter(implementation_status=status)
    return render(request, 'psa/change_request_list.html', {
        'change_requests': qs.order_by('-created_at')[:200],
        'risk_filter': risk,
        'status_filter': status,
    })


@login_required
@require_psa_enabled
def change_request_detail(request, ticket_number):
    """View a CR — plans, schedule, votes, gate state."""
    from accounts.permission_utils import user_has_perm
    if not user_has_perm(request.user, 'change_view'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You don't have the 'change_view' permission.")
    ticket, cr = _get_change_for_ticket(request, ticket_number)
    user_is_required_approver = cr.required_approvers.filter(pk=request.user.pk).exists()
    user_vote = cr.cab_votes.filter(user=request.user).first()
    return render(request, 'psa/change_request_detail.html', {
        'ticket': ticket,
        'cr': cr,
        'votes': cr.cab_votes.select_related('user').all(),
        'required_approvers': cr.required_approvers.all(),
        'user_is_required_approver': user_is_required_approver,
        'user_vote': user_vote,
        'can_create': user_has_perm(request.user, 'change_create'),
        'can_vote': user_has_perm(request.user, 'change_approve_cab') and user_is_required_approver,
        'can_implement': user_has_perm(request.user, 'change_implement') and cr.can_implement(),
        'can_edit': (
            user_has_perm(request.user, 'change_create')
            and cr.implementation_status in {'draft', 'rejected'}
        ),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def change_request_form(request, ticket_number):
    """Edit plans / risk / schedule / required approvers."""
    from accounts.permission_utils import user_has_perm, require_perm  # noqa: F401
    if not user_has_perm(request.user, 'change_create'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You don't have the 'change_create' permission.")
    ticket, cr = _get_change_for_ticket(request, ticket_number)
    if cr.implementation_status not in {'draft', 'rejected'}:
        messages.error(request, f'Cannot edit — change is {cr.get_implementation_status_display()}.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)

    if request.method == 'POST':
        cr.risk = request.POST.get('risk') or cr.risk
        cr.implementation_plan = (request.POST.get('implementation_plan') or '').strip()
        cr.rollback_plan = (request.POST.get('rollback_plan') or '').strip()
        cr.impact_assessment = (request.POST.get('impact_assessment') or '').strip()
        backout = (request.POST.get('backout_window_minutes') or '').strip()
        cr.backout_window_minutes = int(backout) if backout.isdigit() else None
        for fname in ('scheduled_start', 'scheduled_end'):
            val = (request.POST.get(fname) or '').strip()
            if val:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(val)
                setattr(cr, fname, parsed)
            else:
                setattr(cr, fname, None)
        cr.save()
        # Required approvers (m2m)
        approver_ids = request.POST.getlist('required_approvers')
        if approver_ids is not None:
            from django.contrib.auth.models import User as _User
            ids = [int(x) for x in approver_ids if x.isdigit()]
            users = list(_User.objects.filter(id__in=ids))
            cr.required_approvers.set(users)
        AuditLog.log(
            user=request.user, action='update',
            organization=cr.organization,
            object_type='psa.ChangeRequest', object_id=cr.pk,
            object_repr=str(cr),
            description=f'Edited change request for {ticket.ticket_number}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, 'Change request saved.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)

    from django.contrib.auth.models import User as _User
    candidate_users = _User.objects.filter(is_active=True).order_by('username')[:500]
    return render(request, 'psa/change_request_form.html', {
        'ticket': ticket,
        'cr': cr,
        'candidate_users': candidate_users,
        'selected_approver_ids': set(cr.required_approvers.values_list('id', flat=True)),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def change_request_submit(request, ticket_number):
    """Submit a draft change for CAB review."""
    from accounts.permission_utils import user_has_perm
    if not user_has_perm(request.user, 'change_create'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You don't have the 'change_create' permission.")
    ticket, cr = _get_change_for_ticket(request, ticket_number)
    if cr.implementation_status not in {'draft', 'rejected'}:
        messages.error(request, f'Cannot submit — change is {cr.get_implementation_status_display()}.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    # Require plans
    if not cr.implementation_plan.strip():
        messages.error(request, 'Implementation plan is required before submitting.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    if cr.risk in {'high', 'emergency'} and not cr.rollback_plan.strip():
        messages.error(request, 'Rollback plan is required for high or emergency risk changes.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    cr.implementation_status = 'pending_cab'
    cr.submitted_at = timezone.now()
    cr.submitted_by = request.user
    cr.save(update_fields=['implementation_status', 'submitted_at', 'submitted_by', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=cr.organization,
        object_type='psa.ChangeRequest', object_id=cr.pk,
        object_repr=str(cr),
        description=f'Submitted change request for {ticket.ticket_number} to CAB',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, 'Submitted to CAB.')
    return redirect('psa:change_request_detail', ticket_number=ticket_number)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def change_request_vote(request, ticket_number):
    """A CAB member casts (or updates) their vote on a change request."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import CABVote
    if not user_has_perm(request.user, 'change_approve_cab'):
        raise PermissionDenied("You don't have the 'change_approve_cab' permission.")
    ticket, cr = _get_change_for_ticket(request, ticket_number)
    if not cr.required_approvers.filter(pk=request.user.pk).exists():
        raise PermissionDenied('You are not a required approver for this change.')
    if cr.implementation_status not in {'pending_cab', 'approved', 'rejected'}:
        messages.error(
            request,
            f'Cannot vote — change is {cr.get_implementation_status_display()}.',
        )
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    decision = (request.POST.get('decision') or '').strip()
    note = (request.POST.get('note') or '').strip()
    if decision not in {'approved', 'rejected', 'abstained'}:
        messages.error(request, 'Pick Approve, Reject, or Abstain.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    vote, _ = CABVote.objects.update_or_create(
        change_request=cr, user=request.user,
        defaults={'decision': decision, 'note': note},
    )
    # Recompute aggregate state
    if cr.has_cab_rejection:
        cr.implementation_status = 'rejected'
        cr.decided_at = timezone.now()
        cr.decided_by = request.user
        cr.save(update_fields=['implementation_status', 'decided_at', 'decided_by', 'updated_at'])
    elif cr.is_cab_satisfied:
        cr.implementation_status = 'approved'
        cr.decided_at = timezone.now()
        cr.decided_by = request.user
        cr.save(update_fields=['implementation_status', 'decided_at', 'decided_by', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=cr.organization,
        object_type='psa.ChangeRequest', object_id=cr.pk,
        object_repr=str(cr),
        description=f'CAB vote {decision} on change for {ticket.ticket_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Vote recorded: {decision}.')
    return redirect('psa:change_request_detail', ticket_number=ticket_number)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def change_request_implement(request, ticket_number):
    """Begin implementation of an approved change."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'change_implement'):
        raise PermissionDenied("You don't have the 'change_implement' permission.")
    ticket, cr = _get_change_for_ticket(request, ticket_number)
    if not cr.can_implement():
        messages.error(request, 'Change is not yet approved by all CAB members.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    cr.implementation_status = 'implementing'
    cr.actual_start = timezone.now()
    cr.save(update_fields=['implementation_status', 'actual_start', 'updated_at'])
    # Best-effort flip ticket status to In Progress (not all installs have an
    # 'Implementing' status; the CR's own status is the canonical state).
    in_progress_status = (
        TicketStatus.objects.filter(slug='in-progress').first()
        or TicketStatus.objects.filter(is_terminal=False).order_by('sort_order').first()
    )
    if in_progress_status and ticket.status_id != in_progress_status.pk:
        ticket.status = in_progress_status
        ticket.updated_by = request.user
        ticket.save(update_fields=['status', 'updated_by', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=cr.organization,
        object_type='psa.ChangeRequest', object_id=cr.pk,
        object_repr=str(cr),
        description=f'Started implementing change for {ticket.ticket_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, 'Change is now implementing.')
    return redirect('psa:change_request_detail', ticket_number=ticket_number)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def change_request_verify(request, ticket_number):
    """Mark change as verified (successful) and close the ticket."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'change_implement'):
        raise PermissionDenied("You don't have the 'change_implement' permission.")
    ticket, cr = _get_change_for_ticket(request, ticket_number)
    if cr.implementation_status != 'implementing':
        messages.error(request, 'Change must be in Implementing state to verify.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    summary = (request.POST.get('outcome_summary') or '').strip()
    cr.outcome_summary = summary
    cr.implementation_status = 'verified'
    cr.actual_end = timezone.now()
    cr.save(update_fields=['outcome_summary', 'implementation_status', 'actual_end', 'updated_at'])
    closed_status = (
        TicketStatus.objects.filter(slug='closed').first()
        or TicketStatus.objects.filter(is_terminal=True).order_by('sort_order').first()
    )
    if closed_status:
        ticket.status = closed_status
        ticket.closed_at = timezone.now()
        ticket.updated_by = request.user
        ticket.save(update_fields=['status', 'closed_at', 'updated_by', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=cr.organization,
        object_type='psa.ChangeRequest', object_id=cr.pk,
        object_repr=str(cr),
        description=f'Verified change for {ticket.ticket_number}: {summary[:120]}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, 'Change verified and ticket closed.')
    return redirect('psa:change_request_detail', ticket_number=ticket_number)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def change_request_fail(request, ticket_number):
    """Mark change as failed/rolled back."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'change_implement'):
        raise PermissionDenied("You don't have the 'change_implement' permission.")
    ticket, cr = _get_change_for_ticket(request, ticket_number)
    if cr.implementation_status != 'implementing':
        messages.error(request, 'Change must be in Implementing state to fail.')
        return redirect('psa:change_request_detail', ticket_number=ticket_number)
    summary = (request.POST.get('outcome_summary') or '').strip()
    cr.outcome_summary = summary
    cr.implementation_status = 'failed'
    cr.actual_end = timezone.now()
    cr.save(update_fields=['outcome_summary', 'implementation_status', 'actual_end', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=cr.organization,
        object_type='psa.ChangeRequest', object_id=cr.pk,
        object_repr=str(cr),
        description=f'Failed change for {ticket.ticket_number}: {summary[:120]}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.warning(request, 'Change marked as failed / rolled back.')
    return redirect('psa:change_request_detail', ticket_number=ticket_number)


# ---------------------------------------------------------------------------
# Phase 6.2 — Problem records + root-cause analysis
# ---------------------------------------------------------------------------


def _scoped_problem_qs(request):
    """Tenant-scoped Problem queryset following the same staff/org pattern
    as `_scoped_change_request_qs`."""
    from .models import Problem
    qs = Problem.objects.select_related(
        'organization', 'assigned_to', 'investigated_by', 'created_by',
        'duplicate_of', 'fix_change_request',
    )
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        return qs
    if hasattr(request.user, 'memberships'):
        org_ids = list(
            request.user.memberships.filter(is_active=True)
            .values_list('organization_id', flat=True)
        )
        return qs.filter(organization_id__in=org_ids)
    return qs.none()


def _problem_org_choices(request):
    """Orgs the requester is allowed to file a Problem against."""
    from core.models import Organization
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        return Organization.objects.all().order_by('name')
    if hasattr(request.user, 'memberships'):
        org_ids = list(
            request.user.memberships.filter(is_active=True)
            .values_list('organization_id', flat=True)
        )
        return Organization.objects.filter(id__in=org_ids).order_by('name')
    return Organization.objects.none()


@login_required
@require_psa_enabled
def problem_list(request):
    """Filterable Problem queue. Open problems first, then by priority desc,
    then created_at desc."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'problem_view'):
        raise PermissionDenied("You don't have the 'problem_view' permission.")
    from .models import Problem

    qs = _scoped_problem_qs(request)

    status = (request.GET.get('status') or '').strip()
    priority = (request.GET.get('priority') or '').strip()
    assigned = (request.GET.get('assigned') or '').strip()

    valid_statuses = {s for s, _ in Problem.STATUS_CHOICES}
    valid_priorities = {p for p, _ in Problem.PRIORITY_CHOICES}
    if status in valid_statuses:
        qs = qs.filter(status=status)
    if priority in valid_priorities:
        qs = qs.filter(priority=priority)
    if assigned == 'me':
        qs = qs.filter(assigned_to=request.user)
    elif assigned == 'unassigned':
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned.isdigit():
        qs = qs.filter(assigned_to_id=int(assigned))

    # Default sort: open (investigating, known_error) first, then by priority,
    # then created_at desc. Use Case for the open ranking.
    from django.db.models import Case, When, IntegerField, Value
    qs = qs.annotate(
        is_open_rank=Case(
            When(status='investigating', then=Value(0)),
            When(status='known_error', then=Value(1)),
            When(status='resolved', then=Value(2)),
            When(status='closed', then=Value(3)),
            When(status='duplicate', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        ),
        priority_rank=Case(
            When(priority='critical', then=Value(0)),
            When(priority='high', then=Value(1)),
            When(priority='medium', then=Value(2)),
            When(priority='low', then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        ),
    ).order_by('is_open_rank', 'priority_rank', '-created_at')

    return render(request, 'psa/problem_list.html', {
        'problems': qs[:300],
        'status_filter': status,
        'priority_filter': priority,
        'assigned_filter': assigned,
        'status_choices': Problem.STATUS_CHOICES,
        'priority_choices': Problem.PRIORITY_CHOICES,
        'can_create': user_has_perm(request.user, 'problem_create'),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def problem_form(request, pk=None):
    """Create or edit a Problem. Editing allows changing status (gated via
    `can_advance_to`)."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from django.contrib.auth.models import User as _User
    from .models import Problem, ChangeRequest

    if not user_has_perm(request.user, 'problem_create'):
        raise PermissionDenied("You don't have the 'problem_create' permission.")

    is_edit = pk is not None
    problem = None
    if is_edit:
        problem = get_object_or_404(_scoped_problem_qs(request), pk=pk)

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        description = (request.POST.get('description') or '').strip()
        priority = (request.POST.get('priority') or 'medium').strip()
        symptoms = (request.POST.get('symptoms') or '').strip()
        root_cause = (request.POST.get('root_cause') or '').strip()
        workaround = (request.POST.get('workaround') or '').strip()
        permanent_fix = (request.POST.get('permanent_fix') or '').strip()
        org_id = (request.POST.get('organization') or '').strip()
        assigned_to_id = (request.POST.get('assigned_to') or '').strip()
        fix_cr_id = (request.POST.get('fix_change_request') or '').strip()
        duplicate_of_id = (request.POST.get('duplicate_of') or '').strip()

        # 5-whys list — accept a textarea with one why per line
        five_whys_raw = (request.POST.get('five_whys') or '').strip()
        five_whys = [line.strip() for line in five_whys_raw.split('\n') if line.strip()] if five_whys_raw else []

        valid_priorities = {p for p, _ in Problem.PRIORITY_CHOICES}
        if priority not in valid_priorities:
            priority = 'medium'

        if not title:
            messages.error(request, 'Title is required.')
            return redirect(request.path)

        if is_edit:
            problem.title = title
            problem.description = description
            problem.priority = priority
            problem.symptoms = symptoms
            problem.root_cause = root_cause
            problem.workaround = workaround
            problem.permanent_fix = permanent_fix
            problem.five_whys = five_whys

            # Status change is gated through can_advance_to.
            new_status = (request.POST.get('status') or problem.status).strip()
            valid_statuses = {s for s, _ in Problem.STATUS_CHOICES}
            if new_status in valid_statuses and new_status != problem.status:
                # Snapshot RCA fields BEFORE the gate so the saved values
                # (set above) are what feeds the validator.
                if not problem.can_advance_to(new_status):
                    messages.error(
                        request,
                        f'Cannot move to "{new_status}" without the required RCA fields '
                        '(known_error needs root_cause + workaround; '
                        'resolved needs root_cause + permanent_fix).',
                    )
                    return redirect(request.path)
                problem.status = new_status
                if new_status == 'resolved' and not problem.resolved_at:
                    problem.resolved_at = timezone.now()
                if new_status == 'closed' and not problem.closed_at:
                    problem.closed_at = timezone.now()

            # Assignment (optional) — only if the user has problem_assign.
            if user_has_perm(request.user, 'problem_assign'):
                if assigned_to_id.isdigit():
                    try:
                        problem.assigned_to = _User.objects.get(pk=int(assigned_to_id), is_active=True)
                    except _User.DoesNotExist:
                        pass
                elif assigned_to_id == '':
                    problem.assigned_to = None

            # Optional fix_change_request linkage.
            if fix_cr_id.isdigit():
                cr = ChangeRequest.objects.filter(
                    pk=int(fix_cr_id), organization=problem.organization
                ).first()
                problem.fix_change_request = cr
            elif fix_cr_id == '':
                problem.fix_change_request = None

            # Optional duplicate_of linkage.
            if duplicate_of_id.isdigit():
                dup = Problem.objects.filter(pk=int(duplicate_of_id)).exclude(pk=problem.pk).first()
                problem.duplicate_of = dup
            elif duplicate_of_id == '':
                problem.duplicate_of = None

            problem.save()
            AuditLog.log(
                user=request.user, action='update',
                organization=problem.organization,
                object_type='psa.Problem', object_id=problem.pk,
                object_repr=str(problem),
                description=f'Edited problem {problem.problem_number}',
                ip_address=_client_ip(request), path=request.path,
            )
            messages.success(request, 'Problem saved.')
            return redirect('psa:problem_detail', pk=problem.pk)

        # CREATE branch
        org_choices = _problem_org_choices(request)
        try:
            org = org_choices.get(pk=int(org_id)) if org_id.isdigit() else None
        except Exception:
            org = None
        if org is None:
            messages.error(request, 'Pick a client / organization for this problem.')
            return redirect(request.path)

        problem = Problem.objects.create(
            organization=org,
            title=title,
            description=description,
            priority=priority,
            symptoms=symptoms,
            root_cause=root_cause,
            workaround=workaround,
            permanent_fix=permanent_fix,
            five_whys=five_whys,
            created_by=request.user,
        )
        AuditLog.log(
            user=request.user, action='create',
            organization=org,
            object_type='psa.Problem', object_id=problem.pk,
            object_repr=str(problem),
            description=f'Created problem {problem.problem_number}: {title[:120]}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Problem {problem.problem_number} created.')
        return redirect('psa:problem_detail', pk=problem.pk)

    # GET
    org_choices = _problem_org_choices(request)
    candidate_users = _User.objects.filter(is_active=True).order_by('username')[:500]

    fix_cr_choices = []
    if is_edit:
        from .models import ChangeRequest
        fix_cr_choices = ChangeRequest.objects.filter(
            organization=problem.organization,
        ).select_related('ticket').order_by('-created_at')[:200]

    five_whys_text = '\n'.join(problem.five_whys) if (is_edit and problem.five_whys) else ''

    return render(request, 'psa/problem_form.html', {
        'problem': problem,
        'is_edit': is_edit,
        'org_choices': org_choices,
        'candidate_users': candidate_users,
        'fix_cr_choices': fix_cr_choices,
        'five_whys_text': five_whys_text,
        'can_assign': user_has_perm(request.user, 'problem_assign'),
        'can_resolve': user_has_perm(request.user, 'problem_resolve'),
        # Choices for dropdowns
        'priority_choices': [
            ('critical', 'Critical'), ('high', 'High'),
            ('medium', 'Medium'), ('low', 'Low'),
        ],
        'status_choices': [
            ('investigating', 'Investigating'),
            ('known_error', 'Known Error - Workaround Available'),
            ('resolved', 'Resolved - Permanent Fix Deployed'),
            ('closed', 'Closed'),
            ('duplicate', 'Duplicate of Another Problem'),
        ],
    })


@login_required
@require_psa_enabled
def problem_detail(request, pk):
    """Full Problem view: header, RCA, 5-whys, related tickets, notes timeline."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'problem_view'):
        raise PermissionDenied("You don't have the 'problem_view' permission.")
    problem = get_object_or_404(_scoped_problem_qs(request), pk=pk)
    notes = problem.notes.select_related('user').order_by('-created_at')[:100]
    related_tickets = problem.related_tickets.select_related(
        'organization', 'status', 'priority', 'assigned_to'
    ).order_by('-created_at')

    return render(request, 'psa/problem_detail.html', {
        'problem': problem,
        'notes': notes,
        'related_tickets': related_tickets,
        'can_create': user_has_perm(request.user, 'problem_create'),
        'can_assign': user_has_perm(request.user, 'problem_assign'),
        'can_resolve': user_has_perm(request.user, 'problem_resolve'),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def problem_link_ticket(request, pk):
    """Link a Ticket to this Problem by ticket_number."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'problem_create'):
        raise PermissionDenied("You don't have the 'problem_create' permission.")
    problem = get_object_or_404(_scoped_problem_qs(request), pk=pk)
    ticket_number = (request.POST.get('ticket_number') or '').strip()
    if not ticket_number:
        messages.error(request, 'Ticket number is required.')
        return redirect('psa:problem_detail', pk=problem.pk)
    ticket_qs = _scoped_ticket_qs(request).filter(ticket_number=ticket_number)
    ticket = ticket_qs.first()
    if not ticket:
        messages.error(request, f'Ticket {ticket_number} not found (or outside your scope).')
        return redirect('psa:problem_detail', pk=problem.pk)
    if problem.related_tickets.filter(pk=ticket.pk).exists():
        messages.info(request, f'{ticket.ticket_number} is already linked.')
        return redirect('psa:problem_detail', pk=problem.pk)
    problem.related_tickets.add(ticket)
    AuditLog.log(
        user=request.user, action='update',
        organization=problem.organization,
        object_type='psa.Problem', object_id=problem.pk,
        object_repr=str(problem),
        description=f'Linked ticket {ticket.ticket_number} to problem {problem.problem_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Linked {ticket.ticket_number}.')
    # If POST came from a ticket page, redirect back there.
    redirect_to = (request.POST.get('redirect_to') or '').strip()
    if redirect_to == 'ticket':
        return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)
    return redirect('psa:problem_detail', pk=problem.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def problem_unlink_ticket(request, pk, ticket_pk):
    """Remove a ticket from a Problem's related_tickets M2M."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'problem_create'):
        raise PermissionDenied("You don't have the 'problem_create' permission.")
    problem = get_object_or_404(_scoped_problem_qs(request), pk=pk)
    ticket = problem.related_tickets.filter(pk=ticket_pk).first()
    if not ticket:
        messages.info(request, 'That ticket is not linked.')
        return redirect('psa:problem_detail', pk=problem.pk)
    problem.related_tickets.remove(ticket)
    AuditLog.log(
        user=request.user, action='update',
        organization=problem.organization,
        object_type='psa.Problem', object_id=problem.pk,
        object_repr=str(problem),
        description=f'Unlinked ticket {ticket.ticket_number} from problem {problem.problem_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Unlinked {ticket.ticket_number}.')
    return redirect('psa:problem_detail', pk=problem.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def problem_add_note(request, pk):
    """Add an investigation note to a Problem."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import ProblemNote
    if not user_has_perm(request.user, 'problem_create'):
        raise PermissionDenied("You don't have the 'problem_create' permission.")
    problem = get_object_or_404(_scoped_problem_qs(request), pk=pk)
    body = (request.POST.get('body') or '').strip()
    is_breakthrough = (request.POST.get('is_breakthrough') or '').lower() in ('on', '1', 'true', 'yes')
    if not body:
        messages.error(request, 'Note body is required.')
        return redirect('psa:problem_detail', pk=problem.pk)
    ProblemNote.objects.create(
        problem=problem, user=request.user, body=body,
        is_breakthrough=is_breakthrough,
    )
    AuditLog.log(
        user=request.user, action='create',
        organization=problem.organization,
        object_type='psa.ProblemNote', object_id=problem.pk,
        object_repr=str(problem),
        description=f'Added investigation note to problem {problem.problem_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, 'Note added.')
    return redirect('psa:problem_detail', pk=problem.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def problem_advance_status(request, pk):
    """Advance a Problem's status. Validates RCA gates via `can_advance_to`."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import Problem
    if not user_has_perm(request.user, 'problem_resolve'):
        raise PermissionDenied("You don't have the 'problem_resolve' permission.")
    problem = get_object_or_404(_scoped_problem_qs(request), pk=pk)
    new_status = (request.POST.get('status') or '').strip()
    valid = {s for s, _ in Problem.STATUS_CHOICES}
    if new_status not in valid:
        messages.error(request, 'Invalid status.')
        return redirect('psa:problem_detail', pk=problem.pk)
    if not problem.can_advance_to(new_status):
        messages.error(
            request,
            f'Cannot advance to "{new_status}" — RCA fields incomplete '
            '(known_error needs root_cause + workaround; '
            'resolved needs root_cause + permanent_fix).',
        )
        return redirect('psa:problem_detail', pk=problem.pk)
    problem.status = new_status
    if new_status == 'resolved' and not problem.resolved_at:
        problem.resolved_at = timezone.now()
    if new_status == 'closed' and not problem.closed_at:
        problem.closed_at = timezone.now()
    problem.save(update_fields=['status', 'resolved_at', 'closed_at', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=problem.organization,
        object_type='psa.Problem', object_id=problem.pk,
        object_repr=str(problem),
        description=f'Advanced problem {problem.problem_number} to {new_status}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Problem moved to {problem.get_status_display()}.')
    return redirect('psa:problem_detail', pk=problem.pk)


# ---------------------------------------------------------------------------
# Phase 6.3 — Release management + Service-catalog governance
# ---------------------------------------------------------------------------


def _scoped_release_qs(request):
    """Tenant-scoped ReleaseWindow queryset."""
    from .models import ReleaseWindow
    qs = ReleaseWindow.objects.select_related(
        'organization', 'release_manager', 'created_by',
    ).prefetch_related('changes')
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        return qs
    if hasattr(request.user, 'memberships'):
        org_ids = list(
            request.user.memberships.filter(is_active=True)
            .values_list('organization_id', flat=True)
        )
        return qs.filter(organization_id__in=org_ids)
    return qs.none()


def _release_org_choices(request):
    """Orgs the requester is allowed to file a Release against."""
    from core.models import Organization
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        return Organization.objects.all().order_by('name')
    if hasattr(request.user, 'memberships'):
        org_ids = list(
            request.user.memberships.filter(is_active=True)
            .values_list('organization_id', flat=True)
        )
        return Organization.objects.filter(id__in=org_ids).order_by('name')
    return Organization.objects.none()


@login_required
@require_psa_enabled
def release_list(request):
    """Staff queue of release windows, filterable by status."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'release_view'):
        raise PermissionDenied("You don't have the 'release_view' permission.")
    from .models import ReleaseWindow
    qs = _scoped_release_qs(request)
    status = (request.GET.get('status') or '').strip()
    valid_statuses = {s for s, _ in ReleaseWindow.STATUS_CHOICES}
    if status in valid_statuses:
        qs = qs.filter(status=status)
    return render(request, 'psa/release_list.html', {
        'releases': qs[:300],
        'status_filter': status,
        'status_choices': ReleaseWindow.STATUS_CHOICES,
        'can_manage': user_has_perm(request.user, 'release_manage'),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def release_form(request, pk=None):
    """Create or edit a ReleaseWindow."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from django.contrib.auth.models import User as _User
    from django.utils.dateparse import parse_datetime
    from .models import ReleaseWindow

    if not user_has_perm(request.user, 'release_manage'):
        raise PermissionDenied("You don't have the 'release_manage' permission.")

    is_edit = pk is not None
    release = None
    if is_edit:
        release = get_object_or_404(_scoped_release_qs(request), pk=pk)
        if release.is_frozen or release.status in {'completed', 'rolled_back', 'cancelled'}:
            messages.error(request, f'Cannot edit — release is {release.get_status_display()}.')
            return redirect('psa:release_detail', pk=release.pk)

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        description = (request.POST.get('description') or '').strip()
        rollback_plan = (request.POST.get('rollback_plan') or '').strip()
        scheduled_start = (request.POST.get('scheduled_start') or '').strip()
        scheduled_end = (request.POST.get('scheduled_end') or '').strip()
        org_id = (request.POST.get('organization') or '').strip()
        manager_id = (request.POST.get('release_manager') or '').strip()

        if not title:
            messages.error(request, 'Title is required.')
            return redirect(request.path)

        start_dt = parse_datetime(scheduled_start) if scheduled_start else None
        end_dt = parse_datetime(scheduled_end) if scheduled_end else None
        if not start_dt or not end_dt:
            messages.error(request, 'Both scheduled start and scheduled end are required.')
            return redirect(request.path)

        if is_edit:
            release.title = title
            release.description = description
            release.rollback_plan = rollback_plan
            release.scheduled_start = start_dt
            release.scheduled_end = end_dt
            if manager_id.isdigit():
                try:
                    release.release_manager = _User.objects.get(pk=int(manager_id), is_active=True)
                except _User.DoesNotExist:
                    pass
            elif manager_id == '':
                release.release_manager = None
            release.save()
            AuditLog.log(
                user=request.user, action='update',
                organization=release.organization,
                object_type='psa.ReleaseWindow', object_id=release.pk,
                object_repr=str(release),
                description=f'Edited release window {release.release_number}',
                ip_address=_client_ip(request), path=request.path,
            )
            messages.success(request, 'Release saved.')
            return redirect('psa:release_detail', pk=release.pk)

        # CREATE branch
        org_choices = _release_org_choices(request)
        try:
            org = org_choices.get(pk=int(org_id)) if org_id.isdigit() else None
        except Exception:
            org = None
        if org is None:
            messages.error(request, 'Pick a client / organization for this release.')
            return redirect(request.path)

        manager = None
        if manager_id.isdigit():
            try:
                manager = _User.objects.get(pk=int(manager_id), is_active=True)
            except _User.DoesNotExist:
                manager = None

        release = ReleaseWindow.objects.create(
            organization=org,
            title=title,
            description=description,
            rollback_plan=rollback_plan,
            scheduled_start=start_dt,
            scheduled_end=end_dt,
            release_manager=manager,
            created_by=request.user,
        )
        AuditLog.log(
            user=request.user, action='create',
            organization=org,
            object_type='psa.ReleaseWindow', object_id=release.pk,
            object_repr=str(release),
            description=f'Created release window {release.release_number}: {title[:120]}',
            ip_address=_client_ip(request), path=request.path,
        )
        messages.success(request, f'Release {release.release_number} created.')
        return redirect('psa:release_detail', pk=release.pk)

    # GET
    org_choices = _release_org_choices(request)
    candidate_users = _User.objects.filter(is_active=True).order_by('username')[:500]
    return render(request, 'psa/release_form.html', {
        'release': release,
        'is_edit': is_edit,
        'org_choices': org_choices,
        'candidate_users': candidate_users,
    })


@login_required
@require_psa_enabled
def release_detail(request, pk):
    """Full release view with bundled changes + actions."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import ChangeRequest
    if not user_has_perm(request.user, 'release_view'):
        raise PermissionDenied("You don't have the 'release_view' permission.")
    release = get_object_or_404(_scoped_release_qs(request), pk=pk)
    bundled_changes = release.changes.select_related(
        'organization', 'ticket', 'ticket__ticket_type', 'ticket__status',
    ).order_by('-created_at')
    # Candidate changes the user might add: same org, not already in this release.
    candidate_changes = ChangeRequest.objects.filter(
        organization=release.organization,
    ).exclude(release_windows=release).select_related('ticket')[:200]
    return render(request, 'psa/release_detail.html', {
        'release': release,
        'bundled_changes': bundled_changes,
        'candidate_changes': candidate_changes,
        'can_manage': user_has_perm(request.user, 'release_manage'),
        'can_freeze': user_has_perm(request.user, 'release_freeze'),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def release_add_change(request, pk):
    """Add a ChangeRequest to this release."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import ChangeRequest
    if not user_has_perm(request.user, 'release_manage'):
        raise PermissionDenied("You don't have the 'release_manage' permission.")
    release = get_object_or_404(_scoped_release_qs(request), pk=pk)
    if release.is_frozen or release.status in {'completed', 'rolled_back', 'cancelled'}:
        messages.error(request, f'Cannot add changes — release is {release.get_status_display()}.')
        return redirect('psa:release_detail', pk=release.pk)
    change_id = (request.POST.get('change_id') or '').strip()
    if not change_id.isdigit():
        messages.error(request, 'Pick a change to bundle.')
        return redirect('psa:release_detail', pk=release.pk)
    cr = ChangeRequest.objects.filter(
        pk=int(change_id), organization=release.organization,
    ).first()
    if not cr:
        messages.error(request, 'Change not found in this organization.')
        return redirect('psa:release_detail', pk=release.pk)
    # Validate: not already in another active (planned/frozen) release.
    other_active = cr.release_windows.exclude(pk=release.pk).filter(
        status__in=['planned', 'frozen']
    ).first()
    if other_active:
        messages.error(
            request,
            f'That change is already bundled into {other_active.release_number} '
            f'({other_active.get_status_display()}).',
        )
        return redirect('psa:release_detail', pk=release.pk)
    if release.changes.filter(pk=cr.pk).exists():
        messages.info(request, 'That change is already in this release.')
        return redirect('psa:release_detail', pk=release.pk)
    release.changes.add(cr)
    AuditLog.log(
        user=request.user, action='update',
        organization=release.organization,
        object_type='psa.ReleaseWindow', object_id=release.pk,
        object_repr=str(release),
        description=f'Bundled change {cr.ticket.ticket_number} into release {release.release_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Bundled {cr.ticket.ticket_number} into {release.release_number}.')
    return redirect('psa:release_detail', pk=release.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def release_remove_change(request, pk, change_pk):
    """Remove a change from this release."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'release_manage'):
        raise PermissionDenied("You don't have the 'release_manage' permission.")
    release = get_object_or_404(_scoped_release_qs(request), pk=pk)
    if release.is_frozen or release.status in {'completed', 'rolled_back', 'cancelled'}:
        messages.error(request, f'Cannot remove changes — release is {release.get_status_display()}.')
        return redirect('psa:release_detail', pk=release.pk)
    cr = release.changes.filter(pk=change_pk).first()
    if not cr:
        messages.info(request, 'That change is not in this release.')
        return redirect('psa:release_detail', pk=release.pk)
    release.changes.remove(cr)
    AuditLog.log(
        user=request.user, action='update',
        organization=release.organization,
        object_type='psa.ReleaseWindow', object_id=release.pk,
        object_repr=str(release),
        description=f'Removed change {cr.ticket.ticket_number} from release {release.release_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'Removed {cr.ticket.ticket_number} from {release.release_number}.')
    return redirect('psa:release_detail', pk=release.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def release_freeze(request, pk):
    """Flip a release to frozen."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'release_freeze'):
        raise PermissionDenied("You don't have the 'release_freeze' permission.")
    release = get_object_or_404(_scoped_release_qs(request), pk=pk)
    if not release.can_advance_to('frozen'):
        messages.error(
            request,
            'Cannot freeze: release needs at least one bundled change AND a rollback plan.',
        )
        return redirect('psa:release_detail', pk=release.pk)
    release.status = 'frozen'
    release.is_frozen = True
    if not release.actual_start:
        release.actual_start = timezone.now()
    release.save(update_fields=['status', 'is_frozen', 'actual_start', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=release.organization,
        object_type='psa.ReleaseWindow', object_id=release.pk,
        object_repr=str(release),
        description=f'Froze release {release.release_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'{release.release_number} frozen.')
    return redirect('psa:release_detail', pk=release.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def release_complete(request, pk):
    """Mark a release completed."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'release_freeze'):
        raise PermissionDenied("You don't have the 'release_freeze' permission.")
    release = get_object_or_404(_scoped_release_qs(request), pk=pk)
    if not release.can_advance_to('completed'):
        messages.error(
            request,
            f'Cannot complete: release is {release.get_status_display()}.',
        )
        return redirect('psa:release_detail', pk=release.pk)
    release.status = 'completed'
    release.actual_end = timezone.now()
    release.save(update_fields=['status', 'actual_end', 'updated_at'])
    AuditLog.log(
        user=request.user, action='update',
        organization=release.organization,
        object_type='psa.ReleaseWindow', object_id=release.pk,
        object_repr=str(release),
        description=f'Completed release {release.release_number}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'{release.release_number} marked completed.')
    return redirect('psa:release_detail', pk=release.pk)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def release_rollback(request, pk):
    """Mark a release rolled-back with a reason."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    if not user_has_perm(request.user, 'release_freeze'):
        raise PermissionDenied("You don't have the 'release_freeze' permission.")
    release = get_object_or_404(_scoped_release_qs(request), pk=pk)
    if release.status in {'completed', 'rolled_back', 'cancelled'}:
        messages.error(
            request,
            f'Cannot roll back: release is already {release.get_status_display()}.',
        )
        return redirect('psa:release_detail', pk=release.pk)
    reason = (request.POST.get('rolled_back_reason') or '').strip()
    if not reason:
        messages.error(request, 'Rollback reason is required.')
        return redirect('psa:release_detail', pk=release.pk)
    release.status = 'rolled_back'
    release.rolled_back_at = timezone.now()
    release.rolled_back_reason = reason
    release.actual_end = release.actual_end or timezone.now()
    release.save(update_fields=[
        'status', 'rolled_back_at', 'rolled_back_reason', 'actual_end', 'updated_at',
    ])
    AuditLog.log(
        user=request.user, action='update',
        organization=release.organization,
        object_type='psa.ReleaseWindow', object_id=release.pk,
        object_repr=str(release),
        description=f'Rolled back release {release.release_number}: {reason[:120]}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'{release.release_number} marked rolled back.')
    return redirect('psa:release_detail', pk=release.pk)


# ---------------------------------------------------------------------------
# Service Catalog governance — propose / approve / reject ServiceCatalogChange
# ---------------------------------------------------------------------------


# The set of ServiceCatalogItem fields a propose-change form is allowed to
# modify. JSON-serializable so we can store before/after snapshots.
_CATALOG_GOVERNED_FIELDS = (
    'name', 'description', 'default_subject', 'default_body',
    'icon', 'is_active', 'sort_order',
)


def _catalog_snapshot(item):
    """Snapshot the governed fields of a ServiceCatalogItem to a dict."""
    return {f: getattr(item, f) for f in _CATALOG_GOVERNED_FIELDS}


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def catalog_propose_change(request, pk):
    """Propose a change to a ServiceCatalogItem.

    On GET: render a form pre-filled with the live item.
    On POST: create a ServiceCatalogChange row in `pending` state with
    before_snapshot=live values + after_snapshot=submitted values.
    """
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import ServiceCatalogChange
    if not user_has_perm(request.user, 'catalog_propose_change'):
        raise PermissionDenied("You don't have the 'catalog_propose_change' permission.")
    item = get_object_or_404(ServiceCatalogItem, pk=pk)

    if request.method == 'POST':
        before = _catalog_snapshot(item)
        after = dict(before)
        after['name'] = (request.POST.get('name') or item.name).strip()[:120]
        after['description'] = (request.POST.get('description') or '').strip()
        after['default_subject'] = (request.POST.get('default_subject') or '').strip()[:300]
        after['default_body'] = (request.POST.get('default_body') or '').strip()
        after['icon'] = (request.POST.get('icon') or '').strip()[:80]
        after['is_active'] = request.POST.get('is_active') == 'on'
        try:
            after['sort_order'] = int(request.POST.get('sort_order') or 0)
        except ValueError:
            after['sort_order'] = item.sort_order
        reason = (request.POST.get('reason') or '').strip()

        # Discard fields with no diff to keep the snapshot tight.
        after_diff = {k: v for k, v in after.items() if before.get(k) != v}
        if not after_diff:
            messages.info(request, 'No changes detected — nothing to propose.')
            return redirect('psa:service_catalog')

        change = ServiceCatalogChange.objects.create(
            catalog_item=item,
            proposed_by=request.user,
            before_snapshot={k: before[k] for k in after_diff.keys()},
            after_snapshot=after_diff,
            reason=reason,
        )
        AuditLog.log(
            user=request.user, action='create',
            object_type='psa.ServiceCatalogChange', object_id=change.pk,
            object_repr=str(change),
            description=f'Proposed change to catalog item "{item.name}" '
                        f'(fields: {", ".join(after_diff.keys())})',
            ip_address=_client_ip(request), path=request.path,
        )
        # Lightweight notification: email the proposer their proposal is in
        # the pending queue. (More robust notification flows live in
        # psa/notifications.py.)
        try:
            from psa.notifications import _send_email
            _send_email(
                request.user,
                f'Catalog change proposal pending: {item.name}',
                f'Your proposed change to "{item.name}" is awaiting approval.',
            )
        except Exception:
            # notifications are best-effort; never block the response.
            pass
        messages.success(
            request,
            f'Proposal submitted for "{item.name}" — pending approval.',
        )
        return redirect('psa:catalog_change_list')

    return render(request, 'psa/catalog_propose_change.html', {
        'item': item,
    })


@login_required
@require_psa_enabled
def catalog_change_list(request):
    """Queue of pending ServiceCatalogChange proposals (and recent decisions)."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import ServiceCatalogChange
    if not user_has_perm(request.user, 'catalog_propose_change') \
            and not user_has_perm(request.user, 'catalog_approve_change'):
        raise PermissionDenied("You need catalog_propose_change or catalog_approve_change.")
    status = (request.GET.get('status') or 'pending').strip()
    qs = ServiceCatalogChange.objects.select_related(
        'catalog_item', 'proposed_by', 'decided_by',
    )
    valid = {s for s, _ in ServiceCatalogChange.STATUS_CHOICES}
    if status in valid:
        qs = qs.filter(status=status)
    return render(request, 'psa/catalog_change_list.html', {
        'changes': qs[:300],
        'status_filter': status,
        'status_choices': ServiceCatalogChange.STATUS_CHOICES,
        'can_approve': user_has_perm(request.user, 'catalog_approve_change'),
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def catalog_change_decide(request, pk):
    """Approve or reject a pending ServiceCatalogChange."""
    from accounts.permission_utils import user_has_perm
    from django.core.exceptions import PermissionDenied
    from .models import ServiceCatalogChange
    if not user_has_perm(request.user, 'catalog_approve_change'):
        raise PermissionDenied("You don't have the 'catalog_approve_change' permission.")
    change = get_object_or_404(
        ServiceCatalogChange.objects.select_related('catalog_item', 'proposed_by'),
        pk=pk,
    )
    if request.method == 'POST':
        if change.status != 'pending':
            messages.error(request, f'Already decided ({change.get_status_display()}).')
            return redirect('psa:catalog_change_list')
        action = (request.POST.get('action') or '').strip().lower()
        note = (request.POST.get('note') or '').strip()
        if action == 'approve':
            change.decision_note = note
            change.apply(decided_by=request.user)
            AuditLog.log(
                user=request.user, action='update',
                object_type='psa.ServiceCatalogChange', object_id=change.pk,
                object_repr=str(change),
                description=f'Approved + applied catalog change to "{change.catalog_item.name}"',
                ip_address=_client_ip(request), path=request.path,
            )
            messages.success(request, f'Approved + applied change to "{change.catalog_item.name}".')
        elif action == 'reject':
            change.status = 'rejected'
            change.decided_by = request.user
            change.decided_at = timezone.now()
            change.decision_note = note
            change.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
            AuditLog.log(
                user=request.user, action='update',
                object_type='psa.ServiceCatalogChange', object_id=change.pk,
                object_repr=str(change),
                description=f'Rejected catalog change to "{change.catalog_item.name}"',
                ip_address=_client_ip(request), path=request.path,
            )
            messages.success(request, f'Rejected change to "{change.catalog_item.name}".')
        else:
            messages.error(request, 'Pick approve or reject.')
            return redirect('psa:catalog_change_decide', pk=change.pk)
        return redirect('psa:catalog_change_list')

    # GET: render diff view.
    diff_rows = []
    for field in (change.after_snapshot or {}):
        diff_rows.append({
            'field': field,
            'before': (change.before_snapshot or {}).get(field, ''),
            'after': (change.after_snapshot or {}).get(field, ''),
        })
    return render(request, 'psa/catalog_change_decide.html', {
        'change': change,
        'diff_rows': diff_rows,
    })


# ---------------------------------------------------------------------------
# Phase 7 — Outsourcing: share-ticket-to-partner endpoint + inbound webhook
# ---------------------------------------------------------------------------

import hashlib as _phase7_hashlib
import hmac as _phase7_hmac
import json as _phase7_json
import logging as _phase7_logging
import time as _phase7_time

from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

_phase7_log = _phase7_logging.getLogger('psa.outsourcing')


def _phase7_sign(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex digest of the request body."""
    return _phase7_hmac.new(
        (secret or '').encode('utf-8'),
        body,
        _phase7_hashlib.sha256,
    ).hexdigest()


def _phase7_post_to_partner(share, payload: dict) -> dict:
    """Fire an HMAC-signed POST to the partner's webhook. Returns
    {'ok': bool, 'status': int, 'error': str}. Never raises."""
    import urllib.error
    import urllib.request

    partner = share.partner_org
    url = (partner.partner_endpoint_url or '').strip()
    if not url:
        return {'ok': False, 'status': 0, 'error': 'partner has no endpoint URL'}
    body = _phase7_json.dumps(payload).encode('utf-8')
    sig = _phase7_sign(partner.partner_secret, body)
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={
            'Content-Type': 'application/json',
            'X-CST0R-Signature': sig,
            'X-CST0R-Share-Pk': str(share.pk),
            'User-Agent': 'ClientSt0r-Outsourcing/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {'ok': 200 <= resp.status < 300, 'status': resp.status, 'error': ''}
    except urllib.error.HTTPError as e:
        return {'ok': False, 'status': e.code, 'error': str(e)[:200]}
    except Exception as e:
        return {'ok': False, 'status': 0, 'error': str(e)[:200]}


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def ticket_share(request, ticket_number):
    """Share a ticket with an outsourcing partner via HMAC-signed webhook.

    GET  -> render a pick-a-partner form (only orgs with is_outsourcing_partner=True).
    POST -> create TicketShare row + fire HMAC-signed POST to partner_endpoint_url.

    Permission: outsourcing_share_tickets.
    """
    from accounts.permission_utils import user_has_perm
    from core.models import Organization
    from .models import TicketShare

    if not (request.user.is_superuser or user_has_perm(request.user, 'outsourcing_share_tickets')):
        return HttpResponseForbidden('You do not have permission to share tickets to outsourcing partners.')

    ticket = _scoped_ticket_for_write(request, ticket_number)
    partners = Organization.objects.filter(is_outsourcing_partner=True, is_active=True).order_by('name')

    if request.method == 'POST':
        partner_id = request.POST.get('partner_org') or ''
        notes = (request.POST.get('notes') or '').strip()
        try:
            partner = partners.get(pk=partner_id)
        except Organization.DoesNotExist:
            messages.error(request, 'Pick a valid outsourcing partner.')
            return redirect(request.path)

        share, created = TicketShare.objects.get_or_create(
            ticket=ticket, partner_org=partner,
            defaults={
                'shared_by': request.user,
                'notes': notes,
                'status': 'pending',
            },
        )
        if not created:
            messages.warning(request, f'Already shared with {partner.name}.')
            return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

        # Fire HMAC-signed POST to partner endpoint. Failures don't roll back
        # the share row -- the partner has the webhook ID and can re-pull.
        payload = {
            'event': 'ticket_shared',
            'ticket_number': ticket.ticket_number,
            'subject': ticket.subject,
            'description': ticket.description or '',
            'priority': ticket.priority.code if ticket.priority_id else '',
            'partner_secret_token': partner.partner_secret,
            'share_pk': share.pk,
            'notes': notes,
            'ts': int(_phase7_time.time()),
        }
        result = _phase7_post_to_partner(share, payload)
        share.last_synced_at = timezone.now()
        share.save(update_fields=['last_synced_at'])

        AuditLog.log(
            user=request.user, action='create', organization=ticket.organization,
            object_type='psa.TicketShare', object_id=share.pk,
            object_repr=str(share),
            description=f'Shared {ticket.ticket_number} with partner "{partner.name}"',
            ip_address=_client_ip(request), path=request.path,
            extra_data={
                'partner_id': partner.pk,
                'webhook_ok': result.get('ok'),
                'webhook_status': result.get('status'),
                'webhook_error': result.get('error', '')[:200],
            },
        )
        if result.get('ok'):
            messages.success(request, f'Shared with {partner.name}; partner notified.')
        else:
            messages.warning(
                request,
                f'Shared with {partner.name}, but partner webhook failed: '
                f'{result.get("error") or result.get("status")}.',
            )
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    # GET: render form
    existing = ticket.shares.select_related('partner_org').all()
    return render(request, 'psa/ticket_share.html', {
        'ticket': ticket,
        'partners': partners,
        'existing_shares': existing,
    })


@csrf_exempt
@require_http_methods(['POST'])
def ticket_partner_webhook(request, share_pk):
    """Public webhook: accepts comment / status updates from a partner.

    Validates HMAC signature in X-CST0R-Signature header against
    partner_org.partner_secret. Body: {event: 'comment'|'status', payload: {...}}.

      * On 'comment'  -> create a TicketComment with is_internal=False, source='partner'.
      * On 'status'   -> map partner status string to local TicketStatus
                         (best-effort match by slug; fall back to 'in_progress').
    """
    from .models import TicketComment, TicketShare, TicketStatus as _TS

    share = TicketShare.objects.select_related('ticket', 'partner_org').filter(pk=share_pk).first()
    if share is None:
        return JsonResponse({'ok': False, 'error': 'unknown share'}, status=404)

    raw_body = request.body or b''
    raw_body = raw_body[:128 * 1024]  # cap
    sig_header = request.headers.get('X-CST0R-Signature') or request.META.get('HTTP_X_CST0R_SIGNATURE') or ''
    expected = _phase7_sign(share.partner_org.partner_secret or '', raw_body)
    if not (sig_header and _phase7_hmac.compare_digest(sig_header, expected)):
        AuditLog.log(
            user=None, action='access_denied', organization=share.ticket.organization,
            object_type='psa.TicketShare', object_id=share.pk,
            object_repr=str(share),
            description='Partner webhook rejected (bad signature)',
            ip_address=_client_ip(request), path=request.path,
        )
        return HttpResponseForbidden('Invalid signature')

    try:
        data = _phase7_json.loads(raw_body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'ok': False, 'error': 'bad json'}, status=400)

    event = (data.get('event') or '').lower()
    payload = data.get('payload') or {}

    if event == 'comment':
        body = (payload.get('body') or '').strip()
        if not body:
            return JsonResponse({'ok': False, 'error': 'empty comment'}, status=400)
        comment = TicketComment.objects.create(
            ticket=share.ticket,
            body=body,
            is_internal=False,
            is_system=False,
            author_name=(payload.get('author') or share.partner_org.name)[:200],
            author_email=(payload.get('author_email') or '')[:254],
            source='partner',
        )
        share.last_synced_at = timezone.now()
        share.save(update_fields=['last_synced_at'])
        AuditLog.log(
            user=None, action='create', organization=share.ticket.organization,
            object_type='psa.TicketComment', object_id=comment.pk,
            object_repr=f'partner comment on {share.ticket.ticket_number}',
            description=f'Inbound partner comment from {share.partner_org.name}',
            ip_address=_client_ip(request), path=request.path,
            extra_data={'share_pk': share.pk, 'partner_id': share.partner_org_id},
        )
        return JsonResponse({'ok': True, 'comment_id': comment.pk})

    if event == 'status':
        partner_status = (payload.get('status') or '').strip().lower()
        # Best-effort map partner status string to a local slug.
        # Recognised local share statuses get reflected on the share row;
        # any string is also looked up against TicketStatus.slug (case-insensitive).
        share_map = {
            'accepted': 'accepted',
            'declined': 'declined',
            'completed': 'completed',
            'recalled': 'recalled',
            'pending': 'pending',
        }
        if partner_status in share_map:
            now = timezone.now()
            share.status = share_map[partner_status]
            update_fields = ['status', 'last_synced_at']
            share.last_synced_at = now
            if share.status == 'accepted' and not share.accepted_at:
                share.accepted_at = now
                update_fields.append('accepted_at')
            if share.status == 'completed' and not share.completed_at:
                share.completed_at = now
                update_fields.append('completed_at')
            share.save(update_fields=update_fields)

        # Also try to map onto a local Ticket status. Best-effort -- fallback
        # to in_progress if no match. Skip if partner sent a share-only token.
        local = None
        if partner_status and partner_status not in share_map:
            local = _TS.objects.filter(slug__iexact=partner_status).first()
        if local is None:
            local = _TS.objects.filter(slug__in=['in_progress', 'in-progress']).first()
        if local is not None and share.ticket.status_id != local.pk:
            share.ticket.status = local
            share.ticket.save(update_fields=['status', 'updated_at'])
        AuditLog.log(
            user=None, action='update', organization=share.ticket.organization,
            object_type='psa.TicketShare', object_id=share.pk,
            object_repr=str(share),
            description=f'Inbound partner status update from {share.partner_org.name}: {partner_status}',
            ip_address=_client_ip(request), path=request.path,
            extra_data={'share_pk': share.pk, 'partner_status': partner_status},
        )
        return JsonResponse({'ok': True, 'share_status': share.status})

    return JsonResponse({'ok': False, 'error': 'unknown event'}, status=400)


# ---------------------------------------------------------------------------
# Phase 12 v1 (v3.17.231) — Public CSAT response endpoint
# ---------------------------------------------------------------------------

@require_http_methods(['GET', 'POST'])
def csat_respond(request, token):
    """
    Public, token-authenticated CSAT response form. The token is the
    sole auth — recipient doesn't need an account. Single-use:
    re-submitting overwrites the existing rating (treats the latest
    response as authoritative).
    """
    from .models import TicketCSATSurvey
    survey = get_object_or_404(TicketCSATSurvey, token=token)

    if request.method == 'POST':
        try:
            rating = int(request.POST.get('rating') or 0)
        except (TypeError, ValueError):
            rating = 0
        if rating < 1 or rating > 5:
            messages.error(request, 'Pick a rating from 1 to 5.')
            return render(request, 'psa/csat_respond.html', {'survey': survey})
        comment = (request.POST.get('comment') or '').strip()[:2000]
        survey.rating = rating
        survey.comment = comment
        survey.responded_at = timezone.now()
        survey.responded_ip = _client_ip(request)
        survey.save(update_fields=['rating', 'comment', 'responded_at',
                                    'responded_ip'])
        return render(request, 'psa/csat_thanks.html', {'survey': survey})

    return render(request, 'psa/csat_respond.html', {'survey': survey})


# ---------------------------------------------------------------------------
# Phase 25 v1 (v3.17.242) — Timesheet Approval Workflow
# ---------------------------------------------------------------------------

def _week_bounds(d):
    """Return (Monday, Sunday) of the week containing `d`."""
    from datetime import timedelta as _td
    monday = d - _td(days=d.weekday())
    sunday = monday + _td(days=6)
    return monday, sunday


@login_required
@require_psa_enabled
def my_timesheet(request, year=None, week=None):
    """
    Phase 25 (v3.17.242): show the requesting user's time entries for
    a given week and let them submit the bundle for approval.

    URL: /psa/timesheet/                    → current week
         /psa/timesheet/<year>/<week>/      → ISO year+week
    """
    from datetime import date as _date, timedelta as _td
    from .models import TimesheetSubmission, TicketTimeEntry
    if year is None or week is None:
        today = timezone.now().date()
        period_start, period_end = _week_bounds(today)
    else:
        try:
            period_start = _date.fromisocalendar(int(year), int(week), 1)
            period_end = period_start + _td(days=6)
        except (TypeError, ValueError):
            messages.error(request, 'Invalid week identifier.')
            return redirect('psa:my_timesheet')

    entries = (TicketTimeEntry.objects
               .filter(user=request.user,
                       started_at__date__gte=period_start,
                       started_at__date__lte=period_end)
               .select_related('ticket', 'ticket__priority', 'submission')
               .order_by('started_at'))

    submission = (TimesheetSubmission.objects
                  .filter(user=request.user,
                          period_start=period_start, period_end=period_end)
                  .first())

    total_min = sum((e.duration_minutes or 0) for e in entries)
    billable_min = sum((e.duration_minutes or 0) for e in entries if e.is_billable)

    if request.method == 'POST':
        if submission and submission.status in ('approved', 'pending'):
            messages.warning(request, f'Already submitted ({submission.status}).')
            return redirect('psa:my_timesheet_iso', year=period_start.isocalendar()[0],
                            week=period_start.isocalendar()[1])
        if not entries:
            messages.error(request, 'Nothing to submit — log some time first.')
            return redirect('psa:my_timesheet_iso', year=period_start.isocalendar()[0],
                            week=period_start.isocalendar()[1])
        notes = (request.POST.get('notes') or '').strip()[:5000]
        if submission and submission.status == 'rejected':
            submission.status = 'pending'
            submission.submitter_notes = notes
            submission.decided_by = None
            submission.decided_at = None
            submission.decision_notes = ''
            submission.save()
        else:
            submission = TimesheetSubmission.objects.create(
                user=request.user,
                period_start=period_start, period_end=period_end,
                status='pending', submitter_notes=notes,
            )
        entries.update(submission=submission)
        messages.success(request,
            f'Submitted {len(entries)} entries for the week of {period_start}.')
        return redirect('psa:my_timesheet_iso',
                        year=period_start.isocalendar()[0],
                        week=period_start.isocalendar()[1])

    iso_year, iso_week, _iso_day = period_start.isocalendar()
    return render(request, 'psa/my_timesheet.html', {
        'period_start': period_start,
        'period_end': period_end,
        'iso_year': iso_year,
        'iso_week': iso_week,
        'entries': entries,
        'total_minutes': total_min,
        'billable_minutes': billable_min,
        'submission': submission,
    })


@login_required
@require_psa_enabled
def timesheet_approval_queue(request):
    """Staff queue of pending TimesheetSubmissions to approve/reject."""
    from .models import TimesheetSubmission
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not (request.user.is_superuser or is_staff):
        messages.error(request, 'Only staff/superuser can review timesheets.')
        return redirect('core:dashboard')
    pending = (TimesheetSubmission.objects.filter(status='pending')
               .select_related('user').order_by('-submitted_at'))
    decided = (TimesheetSubmission.objects
               .exclude(status__in=['pending', 'draft'])
               .select_related('user', 'decided_by').order_by('-decided_at')[:50])
    return render(request, 'psa/timesheet_approval_queue.html', {
        'pending': pending,
        'decided': decided,
    })


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def timesheet_decide(request, pk):
    """Staff approve / reject a TimesheetSubmission."""
    from .models import TimesheetSubmission
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not (request.user.is_superuser or is_staff):
        messages.error(request, 'Only staff can decide timesheets.')
        return redirect('core:dashboard')
    submission = get_object_or_404(TimesheetSubmission, pk=pk, status='pending')
    decision = request.POST.get('decision') or ''
    notes = (request.POST.get('notes') or '').strip()[:5000]
    if decision == 'approve':
        submission.approve(user=request.user, notes=notes)
        messages.success(request,
            f'Approved {submission.user.username}\'s week of {submission.period_start}.')
    elif decision == 'reject':
        submission.reject(user=request.user, notes=notes)
        messages.success(request,
            f'Rejected {submission.user.username}\'s week of {submission.period_start}; '
            f'their entries are detached so they can fix and re-submit.')
    else:
        messages.error(request, 'Pick approve or reject.')
    return redirect('psa:timesheet_approval_queue')


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def timesheet_bulk_decide(request):
    """
    Phase 25 v2 (v3.17.249): bulk approve / reject TimesheetSubmissions
    by pk. POST `submission_ids` (multi-value) and `decision` (approve | reject).
    Staff/superuser only.
    """
    from .models import TimesheetSubmission
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not (request.user.is_superuser or is_staff):
        messages.error(request, 'Only staff can decide timesheets.')
        return redirect('core:dashboard')
    decision = request.POST.get('decision') or ''
    if decision not in ('approve', 'reject'):
        messages.error(request, 'Pick approve or reject.')
        return redirect('psa:timesheet_approval_queue')
    ids = request.POST.getlist('submission_ids')
    qs = TimesheetSubmission.objects.filter(pk__in=ids, status='pending')
    notes = (request.POST.get('notes') or '').strip()[:5000]
    n = 0
    for sub in qs:
        if decision == 'approve':
            sub.approve(user=request.user, notes=notes)
        else:
            sub.reject(user=request.user, notes=notes)
        n += 1
    if n:
        verb = 'approved' if decision == 'approve' else 'rejected'
        messages.success(request, f'{verb.capitalize()} {n} timesheet{"s" if n != 1 else ""}.')
    else:
        messages.info(request, 'No pending submissions matched.')
    return redirect('psa:timesheet_approval_queue')


@login_required
@require_psa_enabled
def timesheet_payroll_export(request):
    """
    Phase 25 v2 (v3.17.249): payroll CSV export. Returns approved
    TimesheetSubmission rows in a date range, one row per (tech, week)
    with total minutes + billable minutes. Tools like QuickBooks Time /
    Gusto can map this directly.

    Query params:
      ?start=YYYY-MM-DD&end=YYYY-MM-DD
        — period_start within the inclusive range. Defaults to last 30
          days.
    """
    from .models import TimesheetSubmission
    import csv as _csv
    from datetime import date as _date, timedelta as _td
    from django.http import HttpResponse
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not (request.user.is_superuser or is_staff):
        messages.error(request, 'Only staff can export payroll.')
        return redirect('core:dashboard')

    today = _date.today()
    try:
        start = _date.fromisoformat(request.GET.get('start') or
                                     (today - _td(days=30)).isoformat())
        end = _date.fromisoformat(request.GET.get('end') or today.isoformat())
    except ValueError:
        messages.error(request, 'Invalid date range.')
        return redirect('psa:timesheet_approval_queue')

    qs = (TimesheetSubmission.objects
          .filter(status='approved',
                  period_start__gte=start, period_start__lte=end)
          .select_related('user', 'decided_by').order_by('user__username', 'period_start'))

    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = (
        f'attachment; filename="payroll-{start.isoformat()}-to-{end.isoformat()}.csv"'
    )
    w = _csv.writer(resp)
    w.writerow([
        'Username', 'Email', 'Period start', 'Period end',
        'Total minutes', 'Billable minutes', 'Approved at', 'Approved by',
    ])
    for sub in qs:
        w.writerow([
            sub.user.username,
            sub.user.email or '',
            sub.period_start.isoformat(),
            sub.period_end.isoformat(),
            sub.total_minutes,
            sub.total_billable_minutes,
            sub.decided_at.isoformat() if sub.decided_at else '',
            sub.decided_by.username if sub.decided_by_id else '',
        ])
    return resp


# ---------------------------------------------------------------------------
# Phase 46 (v3.17.533) — job kit: what the tech has to take to the job
# ---------------------------------------------------------------------------

def _kit_ticket(request, ticket_number):
    """Fetch a ticket for kit editing, scoped exactly as ticket_detail is.

    Reuses `_scoped_ticket_qs` plus the same cross-org refusal, so the kit
    endpoints cannot become a way to reach a ticket the detail page would hide.
    """
    org = get_request_organization(request)
    ticket = get_object_or_404(_scoped_ticket_qs(request),
                               ticket_number=ticket_number)
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        if ticket.organization_id != getattr(org, 'id', None):
            raise Http404('Ticket not found')
    return ticket


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_kit_add(request, ticket_number):
    """Add one line to the kit list."""
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    from psa.models import TicketKitItem

    ticket = _kit_ticket(request, ticket_number)
    kind = request.POST.get('kind') or ''
    if kind not in dict(TicketKitItem.KIND_CHOICES):
        messages.error(request, 'Pick what kind of item this is.')
        return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)

    try:
        quantity = max(1, int(request.POST.get('quantity') or 1))
    except (TypeError, ValueError):
        quantity = 1

    item = TicketKitItem(
        organization=ticket.organization, ticket=ticket, kind=kind,
        quantity=quantity,
        description=(request.POST.get('description') or '').strip()[:255],
        notes=(request.POST.get('notes') or '').strip()[:255],
    )

    # Resolve the referenced row within the ticket's own organization — a tool
    # id from another tenant must not attach here.
    if kind == TicketKitItem.KIND_TOOL:
        item.tool = Tool.objects.for_organization(
            ticket.organization).filter(pk=request.POST.get('tool') or 0).first()
    elif kind == TicketKitItem.KIND_INVENTORY:
        item.inventory_item = InventoryItem.objects.for_organization(
            ticket.organization).filter(
                pk=request.POST.get('inventory_item') or 0).first()

    try:
        item.full_clean(exclude=['organization', 'ticket'])
        # The save needs its own savepoint. Catching IntegrityError without one
        # leaves the surrounding transaction broken, so every later query in the
        # request — including rendering the redirect target — fails too. The
        # duplicate is an expected outcome here, not an exceptional one.
        with transaction.atomic():
            item.save()
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
    except IntegrityError:
        messages.warning(
            request,
            'That is already on the list — change its quantity instead of '
            'adding a second line.')
    else:
        messages.success(request, f'Added {item.label} to the kit list.')
    return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_kit_remove(request, ticket_number, pk):
    ticket = _kit_ticket(request, ticket_number)
    removed = ticket.kit_items.filter(pk=pk).first()
    if removed:
        label = removed.label
        removed.delete()
        messages.success(request, f'Removed {label}.')
    return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def ticket_kit_toggle_packed(request, ticket_number, pk):
    """Tick a line off while loading the van, or untick it."""
    from django.utils import timezone as _tz

    ticket = _kit_ticket(request, ticket_number)
    item = get_object_or_404(ticket.kit_items, pk=pk)
    item.packed = not item.packed
    item.packed_at = _tz.now() if item.packed else None
    item.packed_by = request.user if item.packed else None
    item.save(update_fields=['packed', 'packed_at', 'packed_by', 'updated_at'])

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'packed': item.packed})
    return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)


# ---------------------------------------------------------------------------
# Phase 35.1 (v3.17.548) — project templates
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
def project_template_list(request):
    from .models import ProjectTemplate
    org = get_request_organization(request)
    qs = ProjectTemplate.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    return render(request, 'psa/project_template_list.html', {
        'templates': qs.prefetch_related('template_tasks').order_by('name'),
    })


@login_required
@require_psa_enabled
def project_template_detail(request, pk):
    from .models import ProjectTemplate, ProjectTemplateTask

    org = get_request_organization(request)
    qs = ProjectTemplate.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    template = get_object_or_404(qs, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action') or 'save'

        if action == 'add_task':
            title = (request.POST.get('title') or '').strip()[:300]
            if not title:
                messages.error(request, 'A task needs a title.')
                return redirect('psa:project_template_detail', pk=template.pk)
            hours = request.POST.get('estimated_hours') or None
            offset = request.POST.get('due_offset_days')
            ProjectTemplateTask.objects.create(
                template=template,
                title=title,
                description=(request.POST.get('description') or '').strip(),
                is_milestone=request.POST.get('is_milestone') == 'on',
                estimated_hours=hours or None,
                # Written out rather than `or None`, which would read a
                # submitted 0 — "due on the start date" — as "no date".
                due_offset_days=(int(offset) if (offset or '').strip() else None),
                sort_order=template.template_tasks.count(),
            )
            messages.success(request, 'Task added to the template.')
            return redirect('psa:project_template_detail', pk=template.pk)

        if action == 'delete_task':
            task = template.template_tasks.filter(
                pk=request.POST.get('task_id')).first()
            if task:
                task.delete()
                messages.success(request, 'Task removed from the template.')
            return redirect('psa:project_template_detail', pk=template.pk)

        if action == 'delete':
            template.delete()
            messages.success(
                request,
                'Template deleted. Projects already built from it keep their '
                'tasks — they were copied, not linked.')
            return redirect('psa:project_template_list')

        template.name = (request.POST.get('name') or template.name).strip()[:200]
        template.description = (request.POST.get('description') or '').strip()
        template.is_active = request.POST.get('is_active') == 'on'
        template.save()
        messages.success(request, 'Template saved.')
        return redirect('psa:project_template_detail', pk=template.pk)

    return render(request, 'psa/project_template_detail.html', {
        'template': template,
        'tasks': template.template_tasks.order_by('sort_order', 'id'),
    })


@login_required
@require_psa_enabled
def project_template_create(request):
    from .models import ProjectTemplate

    org = get_request_organization(request)
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()[:200]
        if not name:
            messages.error(request, 'A template needs a name.')
            return redirect('psa:project_template_list')
        if org is None:
            messages.error(
                request,
                'Pick an organization before creating a template — a template '
                'belongs to the MSP that owns it.')
            return redirect('psa:project_template_list')
        if ProjectTemplate.objects.filter(organization=org, name=name).exists():
            messages.error(request, 'A template with that name already exists.')
            return redirect('psa:project_template_list')
        template = ProjectTemplate.objects.create(
            organization=org, name=name,
            description=(request.POST.get('description') or '').strip(),
            created_by=request.user,
        )
        messages.success(request, 'Template created. Add its tasks below.')
        return redirect('psa:project_template_detail', pk=template.pk)
    return redirect('psa:project_template_list')


@login_required
@require_psa_enabled
def project_apply_template(request, pk):
    """Copy a template's tasks onto an existing project."""
    from .models import Project, ProjectTemplate

    org = get_request_organization(request)
    qs = Project.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    project = get_object_or_404(qs, pk=pk)

    if request.method != 'POST':
        return redirect('psa:project_detail', pk=project.pk)

    template = ProjectTemplate.objects.filter(
        pk=request.POST.get('template'),
        organization=project.organization).first()
    if template is None:
        messages.error(request, 'That template is not available for this project.')
        return redirect('psa:project_detail', pk=project.pk)

    created = template.apply_to(project, created_by=request.user)
    messages.success(
        request,
        f'Added {len(created)} task(s) from "{template.name}". They are copies — '
        f'editing the template later will not change this project.')
    return redirect('psa:project_detail', pk=project.pk)


# ---------------------------------------------------------------------------
# Phase 35.4 (v3.17.550) — spawn a ticket from a project task
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
def project_task_to_ticket(request, task_pk):
    """Create a ticket for a project task, and link the two.

    A task and a ticket are not the same thing and this does not try to merge
    them: the task stays the unit of project planning, the ticket becomes the
    unit of work with time, SLA and comments hanging off it. The link is the
    task's existing `related_ticket`.
    """
    from .models import Project, ProjectTask, Queue, Ticket, TicketPriority, TicketStatus, TicketType

    org = get_request_organization(request)
    qs = ProjectTask.objects.select_related('project', 'assigned_to')
    if org is not None:
        qs = qs.filter(project__organization=org)
    task = get_object_or_404(qs, pk=task_pk)

    if request.method != 'POST':
        return redirect('psa:project_detail', pk=task.project_id)

    # One ticket per task. A second would split the time entries across two
    # records and quietly break the project's actual-hours figure.
    if task.related_ticket_id:
        messages.info(
            request,
            f'This task already has ticket {task.related_ticket.ticket_number}.')
        return redirect('psa:project_detail', pk=task.project_id)

    project = task.project
    status = (TicketStatus.objects.filter(slug='new').first()
              or TicketStatus.objects.first())
    queue = Queue.objects.first()
    priority = TicketPriority.objects.first()
    ticket_type = TicketType.objects.first()
    if not all([status, queue, priority, ticket_type]):
        messages.error(
            request,
            'Ticket defaults are missing — seed the PSA reference data first.')
        return redirect('psa:project_detail', pk=project.pk)

    ticket = Ticket.objects.create(
        organization=project.organization,
        subject=task.title[:300],
        description=task.description,
        project=project,
        status=status,
        queue=queue,
        priority=priority,
        ticket_type=ticket_type,
        assigned_to=task.assigned_to,
        source='manual',
    )
    # The ticket inherits the task's due date as its resolution target: a task
    # due Friday whose ticket has no date would drop off every SLA view.
    if task.due_date:
        from datetime import datetime, time as _time
        ticket.resolution_due_at = timezone.make_aware(
            datetime.combine(task.due_date, _time(17, 0)))
        ticket.save(update_fields=['resolution_due_at'])

    task.related_ticket = ticket
    task.save(update_fields=['related_ticket', 'updated_at'])

    AuditLog.log(
        user=request.user, action='create',
        organization=project.organization,
        object_type='psa.Ticket', object_id=ticket.pk,
        object_repr=ticket.ticket_number,
        description=f'Created from project task "{task.title}"',
        ip_address=_client_ip(request), path=request.path,
    )

    messages.success(
        request,
        f'Created {ticket.ticket_number} from "{task.title}". Time logged on it '
        f'counts towards this project\'s actuals.')
    return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)


# ---------------------------------------------------------------------------
# Phase 35.5 (v3.17.554) — timeline / Gantt view
# ---------------------------------------------------------------------------

def _timeline_rows(project):
    """Task bars positioned as percentages across the project's date span.

    Percentages rather than pixels so the chart is responsive without
    JavaScript having to lay it out — the browser already knows how wide the
    container is and CSS can do the rest.
    """
    from datetime import timedelta

    tasks = list(
        project.tasks.select_related('assigned_to')
        .prefetch_related('depends_on')
        .order_by('sort_order', 'id')
    )
    scheduled = [t for t in tasks if t.is_scheduled]
    if not scheduled:
        return {'rows': [], 'unscheduled': tasks, 'start': None, 'end': None,
                'days': 0, 'months': []}

    start = min(t.bar_start for t in scheduled)
    end = max(t.bar_end for t in scheduled)
    # A project whose tasks all fall on one day would divide by zero; give it
    # a day of width so the bar has somewhere to sit.
    span_days = max((end - start).days + 1, 1)

    rows = []
    index_by_id = {}
    for position, task in enumerate(scheduled):
        offset = (task.bar_start - start).days
        width = max((task.bar_end - task.bar_start).days + 1, 1)
        index_by_id[task.pk] = position
        rows.append({
            'task': task,
            'left_percent': round(offset * 100.0 / span_days, 4),
            'width_percent': round(width * 100.0 / span_days, 4),
            'position': position,
            'is_blocked': task.is_blocked,
            'depends_on_ids': [d.pk for d in task.depends_on.all()],
        })

    # Dependency arrows, as (from_row, to_row) pairs the template can draw
    # between. Edges pointing at an unscheduled task are dropped rather than
    # drawn to nowhere.
    edges = []
    for row in rows:
        for dep_id in row['depends_on_ids']:
            if dep_id in index_by_id:
                edges.append({'from': index_by_id[dep_id], 'to': row['position']})

    # Month labels across the top.
    months = []
    cursor = start.replace(day=1)
    while cursor <= end:
        offset = max((cursor - start).days, 0)
        months.append({
            'label': cursor.strftime('%b %Y'),
            'left_percent': round(offset * 100.0 / span_days, 4),
        })
        cursor = (cursor + timedelta(days=32)).replace(day=1)

    return {
        'rows': rows,
        'edges': edges,
        'unscheduled': [t for t in tasks if not t.is_scheduled],
        'start': start,
        'end': end,
        'days': span_days,
        'months': months,
    }


@login_required
@require_psa_enabled
def project_timeline(request, pk):
    """Gantt-style plan for one project."""
    org = get_request_organization(request)
    qs = Project.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    project = get_object_or_404(qs, pk=pk)

    context = _timeline_rows(project)
    context['item'] = project
    return render(request, 'psa/project_timeline.html', context)


@login_required
@require_psa_enabled
def project_task_reschedule(request, task_pk):
    """Move a task's bar. Backs the drag handler and the date inputs alike."""
    from datetime import date as _date

    from .models import ProjectTask

    org = get_request_organization(request)
    qs = ProjectTask.objects.select_related('project')
    if org is not None:
        qs = qs.filter(project__organization=org)
    task = get_object_or_404(qs, pk=task_pk)

    if request.method != 'POST':
        return redirect('psa:project_timeline', pk=task.project_id)

    def _parse(name):
        raw = (request.POST.get(name) or '').strip()
        if not raw:
            return None, False
        try:
            return _date.fromisoformat(raw), True
        except ValueError:
            return None, False

    start, start_ok = _parse('start_date')
    due, due_ok = _parse('due_date')

    if not start_ok and not due_ok:
        messages.error(request, 'Give the task a start date, a due date, or both.')
        return redirect('psa:project_timeline', pk=task.project_id)

    if start and due and due < start:
        messages.error(request, 'A task cannot be due before it starts.')
        return redirect('psa:project_timeline', pk=task.project_id)

    task.start_date = start
    task.due_date = due
    task.save(update_fields=['start_date', 'due_date', 'updated_at'])

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({
            'ok': True,
            'start_date': start.isoformat() if start else None,
            'due_date': due.isoformat() if due else None,
        })

    messages.success(request, f'Rescheduled "{task.title}".')
    return redirect('psa:project_timeline', pk=task.project_id)


@login_required
@require_psa_enabled
def project_task_dependency(request, task_pk):
    """Add or remove a "must finish first" edge between two tasks."""
    from .models import ProjectTask

    org = get_request_organization(request)
    qs = ProjectTask.objects.select_related('project')
    if org is not None:
        qs = qs.filter(project__organization=org)
    task = get_object_or_404(qs, pk=task_pk)

    if request.method != 'POST':
        return redirect('psa:project_timeline', pk=task.project_id)

    other = ProjectTask.objects.filter(
        pk=request.POST.get('depends_on'), project=task.project).first()
    if other is None:
        messages.error(request, 'That task is not part of this project.')
        return redirect('psa:project_timeline', pk=task.project_id)

    if request.POST.get('action') == 'remove':
        task.depends_on.remove(other)
        messages.success(request, 'Dependency removed.')
        return redirect('psa:project_timeline', pk=task.project_id)

    if task.add_dependency(other):
        messages.success(
            request, f'"{task.title}" now waits for "{other.title}".')
    else:
        messages.error(
            request,
            'That would create a circular dependency — the two tasks would '
            'each be waiting for the other.')
    return redirect('psa:project_timeline', pk=task.project_id)


@login_required
@require_psa_enabled
def project_generate_invoice(request, pk):
    """Phase 35.6 (v3.17.555): raise a draft invoice from a project."""
    org = get_request_organization(request)
    qs = Project.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    project = get_object_or_404(qs, pk=pk)

    if request.method != 'POST':
        return redirect('psa:project_detail', pk=project.pk)

    invoice, message = project.generate_invoice(created_by=request.user)
    if invoice is None:
        messages.error(request, message)
        return redirect('psa:project_detail', pk=project.pk)

    AuditLog.log(
        user=request.user, action='create',
        organization=project.organization,
        object_type='psa.Invoice', object_id=invoice.pk,
        object_repr=invoice.invoice_number,
        description=f'Generated from project "{project.name}"',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, f'{message} It is a draft — nothing has been sent.')
    return redirect('psa:invoice_detail', pk=invoice.pk)
