"""
Process views - CRUD operations for processes
"""
import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.forms import inlineformset_factory
from django.db.models import Q, Count

from core.middleware import get_request_organization

logger = logging.getLogger('processes')
from .models import Process, ProcessStage, ProcessExecution, ProcessStageCompletion, ProcessExecutionAuditLog
from .forms import ProcessForm, ProcessStageFormSet, ProcessExecutionForm


def is_superuser(user):
    return user.is_superuser


@login_required
def process_list(request):
    """List all processes (org + global) or all processes across all orgs in global view"""
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: show all processes across all organizations
        processes = Process.objects.filter(
            is_published=True,
            is_archived=False
        ).select_related('organization', 'created_by').prefetch_related('tags')
    elif not org:
        # No org and not in global view — need org context.
        # v3.17.169 — clearer message; non-staff users without an active org
        # have no way to scope this list, so we still redirect them.
        messages.error(request,
            'Switch to a specific organization first to see its workflows.')
        return redirect('accounts:organization_list')
    else:
        # Organization view: get org processes + global processes
        processes = Process.objects.filter(
            Q(organization=org) | Q(is_global=True),
            is_published=True,
            is_archived=False
        ).select_related('created_by').prefetch_related('tags')

    # Filter by category
    category = request.GET.get('category')
    if category:
        processes = processes.filter(category=category)

    # Search
    q = request.GET.get('q')
    if q:
        processes = processes.filter(
            Q(title__icontains=q) | Q(description__icontains=q)
        )

    return render(request, 'processes/process_list.html', {
        'processes': processes,
        'current_organization': org,
        'categories': Process.CATEGORY_CHOICES,
        'selected_category': category,
        'in_global_view': in_global_view,
        # Only superusers should see the "View All Executions" link — regular
        # users should access workflow runs through the linked PSA tickets.
        'show_executions_link': request.user.is_superuser,
    })


@login_required
def process_detail(request, slug):
    """View process details with all stages"""
    org = get_request_organization(request)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if not org and not in_global_view:
        # v3.17.169 — clearer message for non-staff in Global view (which
        # they shouldn't see, but defense-in-depth).
        messages.error(request,
            'Switch to a specific organization first to view this workflow.')
        return redirect('accounts:organization_list')

    if in_global_view:
        process = get_object_or_404(Process, slug=slug)
    else:
        process = get_object_or_404(
            Process.objects.filter(Q(organization=org) | Q(is_global=True)),
            slug=slug
        )

    # Get all stages with linked entities
    stages = process.stages.all().select_related(
        'linked_document',
        'linked_password',
        'linked_asset',
        'linked_secure_note'
    )

    # Get user's active executions for this process (only when org context exists)
    my_executions = ProcessExecution.objects.filter(
        process=process,
        organization=org,
        assigned_to=request.user,
        status__in=['not_started', 'in_progress']
    ) if org else ProcessExecution.objects.none()

    return render(request, 'processes/process_detail.html', {
        'process': process,
        'stages': stages,
        'current_organization': org,
        'my_executions': my_executions,
        'in_global_view': in_global_view,
    })


@login_required
@require_http_methods(["POST"])
def process_generate_diagram(request, slug):
    """
    AJAX endpoint to generate/regenerate flowchart diagram for a workflow.
    """
    from django.http import JsonResponse
    from .models import Process
    from docs.models import Diagram
    import xml.etree.ElementTree as ET

    org = get_request_organization(request)
    process = get_object_or_404(Process, slug=slug, organization=org)

    try:
        # Generate diagram XML from workflow stages
        diagram_xml = _generate_flowchart_xml_from_process(process)

        # Create or update diagram
        if process.linked_diagram:
            # Update existing diagram
            diagram = process.linked_diagram
            diagram.diagram_xml = diagram_xml
            diagram.description = f'Auto-generated flowchart for {process.title} (Updated: {timezone.now().strftime("%Y-%m-%d %H:%M")})'
            diagram.save()
            message = f'✓ Flowchart diagram regenerated successfully!'
        else:
            # Create new diagram
            diagram = Diagram.objects.create(
                organization=org,
                title=f'{process.title} - Flowchart',
                slug=f'{process.slug}-flowchart',
                diagram_type='flowchart',
                diagram_xml=diagram_xml,
                description=f'Auto-generated flowchart for {process.title}',
                created_by=request.user,
            )
            process.linked_diagram = diagram
            process.save()
            message = f'✓ Flowchart diagram generated successfully!'

        return JsonResponse({
            'success': True,
            'message': message,
            'diagram_slug': diagram.slug,
            'diagram_url': f'/docs/diagrams/{diagram.slug}/'
        })

    except Exception as e:
        logger.error(f"Error generating diagram for workflow {slug}: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def _generate_flowchart_xml_from_process(process):
    """Generate draw.io XML for a flowchart based on process/workflow steps."""
    from .models import ProcessStage

    stages = process.stages.all().order_by('order')

    # Draw.io XML template
    xml_template = '''<mxfile host="app.diagrams.net">
  <diagram name="Page-1" id="workflow-{workflow_id}">
    <mxGraphModel dx="800" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="850" pageHeight="1100">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        {shapes}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>'''

    shapes = []
    current_id = 2
    y_position = 60
    x_position = 325
    shape_height = 80
    shape_width = 200
    spacing = 120

    # Start node
    shapes.append(f'''
        <mxCell id="{current_id}" value="Start: {process.title[:30]}" style="ellipse;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
          <mxGeometry x="{x_position}" y="{y_position}" width="{shape_width}" height="60" as="geometry" />
        </mxCell>''')
    prev_id = current_id
    current_id += 1
    y_position += 60 + spacing

    # Process stages
    for idx, stage in enumerate(stages):
        fill_color = "#dae8fc" if idx % 2 == 0 else "#fff2cc"
        stroke_color = "#6c8ebf" if idx % 2 == 0 else "#d6b656"

        stage_label = stage.title[:40]
        if stage.requires_confirmation:
            # Diamond for decision points
            shapes.append(f'''
        <mxCell id="{current_id}" value="{stage_label}?" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff3cd;strokeColor=#ffc107;" vertex="1" parent="1">
          <mxGeometry x="{x_position - 50}" y="{y_position}" width="{shape_width + 100}" height="{shape_height + 20}" as="geometry" />
        </mxCell>''')
            y_offset = shape_height + 20
        else:
            # Rectangle for standard steps
            shapes.append(f'''
        <mxCell id="{current_id}" value="{stage_label}" style="rounded=1;whiteSpace=wrap;html=1;fillColor={fill_color};strokeColor={stroke_color};" vertex="1" parent="1">
          <mxGeometry x="{x_position}" y="{y_position}" width="{shape_width}" height="{shape_height}" as="geometry" />
        </mxCell>''')
            y_offset = shape_height

        # Connection from previous
        shapes.append(f'''
        <mxCell id="{current_id + 1}" value="" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="{prev_id}" target="{current_id}">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>''')

        prev_id = current_id
        current_id += 2
        y_position += y_offset + spacing

    # End node
    shapes.append(f'''
        <mxCell id="{current_id}" value="End" style="ellipse;whiteSpace=wrap;html=1;fillColor=#f8d7da;strokeColor=#dc3545;" vertex="1" parent="1">
          <mxGeometry x="{x_position}" y="{y_position}" width="{shape_width}" height="60" as="geometry" />
        </mxCell>''')

    # Final connection
    shapes.append(f'''
        <mxCell id="{current_id + 1}" value="" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="{prev_id}" target="{current_id}">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>''')

    # Build final XML
    diagram_xml = xml_template.format(
        workflow_id=process.id,
        shapes=''.join(shapes)
    )

    return diagram_xml


@login_required
def process_create(request):
    """Create new process"""
    from core.models import Organization

    org = get_request_organization(request)

    # v3.17.169 — in Global view, render the form with an org picker instead
    # of bouncing the user back to the org list. The picked org becomes the
    # `organization` for this new Process.
    needs_org_pick = False
    org_choices = None
    if not org:
        is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
        if request.user.is_superuser or is_staff:
            org_choices = Organization.objects.filter(is_active=True).order_by('name')
        else:
            from accounts.models import Membership
            org_ids = Membership.objects.filter(
                user=request.user, is_active=True
            ).values_list('organization_id', flat=True)
            org_choices = Organization.objects.filter(
                pk__in=org_ids, is_active=True
            ).order_by('name')
        if not org_choices.exists():
            messages.error(request,
                'You must be a member of at least one organization to create a process.')
            return redirect('accounts:organization_list')
        if request.method == 'POST':
            picked = (request.POST.get('selected_org_id') or '').strip()
            if picked:
                try:
                    org = org_choices.get(pk=int(picked))
                except (Organization.DoesNotExist, ValueError, TypeError):
                    org = None
        needs_org_pick = org is None

    if needs_org_pick:
        if request.method == 'POST':
            messages.error(request,
                'Please pick an organization to own this process.')
        return render(request, 'processes/process_form.html', {
            'form': ProcessForm(),
            'formset': ProcessStageFormSet(),
            'action': 'Create',
            'current_organization': None,
            'org_choices': org_choices,
            'needs_org_pick': True,
        })

    if request.method == 'POST':
        form = ProcessForm(request.POST, organization=org)
        formset = ProcessStageFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            process = form.save(commit=False)
            process.organization = org
            process.created_by = request.user
            process.last_modified_by = request.user
            process.save()
            form.save_m2m()

            # Save stages
            formset.instance = process
            formset.save()

            messages.success(request, f"Process '{process.title}' created successfully.")
            return redirect('processes:process_detail', slug=process.slug)
    else:
        form = ProcessForm(organization=org)
        formset = ProcessStageFormSet()

    return render(request, 'processes/process_form.html', {
        'form': form,
        'formset': formset,
        'action': 'Create',
        'current_organization': org,
    })


@login_required
def process_edit(request, slug):
    """Edit existing process"""
    org = get_request_organization(request)

    # v3.17.169 — in Global view, fall back to the process's own organization
    # (only superusers/staff reach this branch via the global-view check).
    # For everyone else, no-org still bounces because they shouldn't be
    # editing arbitrary org processes from outside an org context.
    if not org:
        is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
        if request.user.is_superuser or is_staff:
            process = get_object_or_404(Process, slug=slug)
            org = process.organization
        else:
            messages.error(request,
                'Switch to a specific organization first to edit this process.')
            return redirect('accounts:organization_list')
    else:
        process = get_object_or_404(Process, slug=slug, organization=org)

    if request.method == 'POST':
        form = ProcessForm(request.POST, instance=process, organization=org)
        formset = ProcessStageFormSet(request.POST, instance=process)

        if form.is_valid() and formset.is_valid():
            process = form.save(commit=False)
            process.last_modified_by = request.user
            process.save()
            form.save_m2m()

            formset.save()

            messages.success(request, f"Process '{process.title}' updated successfully.")
            return redirect('processes:process_detail', slug=process.slug)
    else:
        form = ProcessForm(instance=process, organization=org)
        formset = ProcessStageFormSet(instance=process)

    return render(request, 'processes/process_form.html', {
        'form': form,
        'formset': formset,
        'process': process,
        'action': 'Edit',
        'current_organization': org,
    })


@login_required
def process_delete(request, slug):
    """Delete process"""
    org = get_request_organization(request)

    # v3.17.169 — Global-view superuser/staff: fall back to the process's own
    # organization. Everyone else: helpful redirect with a clearer message.
    if not org:
        is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
        if request.user.is_superuser or is_staff:
            process = get_object_or_404(Process, slug=slug)
            org = process.organization
        else:
            messages.error(request,
                'This action requires you to switch to a specific organization first.')
            return redirect('accounts:organization_list')
    else:
        process = get_object_or_404(Process, slug=slug, organization=org)

    if request.method == 'POST':
        title = process.title
        process.delete()
        messages.success(request, f"Process '{title}' deleted successfully.")
        return redirect('processes:process_list')

    # Check if process has active executions
    active_executions = ProcessExecution.objects.filter(
        process=process,
        status__in=['not_started', 'in_progress']
    ).count()

    return render(request, 'processes/process_confirm_delete.html', {
        'process': process,
        'active_executions': active_executions,
        'current_organization': org,
    })


# Global Processes (Superuser only)
@login_required
@user_passes_test(is_superuser)
def global_process_list(request):
    """List global processes (superuser only)"""
    processes = Process.objects.filter(is_global=True).select_related('created_by')
    
    return render(request, 'processes/global_process_list.html', {
        'processes': processes,
        'categories': Process.CATEGORY_CHOICES,
    })


@login_required
@user_passes_test(is_superuser)
def global_process_create(request):
    """Create global process (superuser only)"""
    if request.method == 'POST':
        form = ProcessForm(request.POST, is_global=True)
        formset = ProcessStageFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            process = form.save(commit=False)
            process.is_global = True
            process.created_by = request.user
            process.last_modified_by = request.user
            # Use a default org (first one) for global processes
            from core.models import Organization
            process.organization = Organization.objects.first()
            process.save()
            form.save_m2m()

            formset.instance = process
            formset.save()

            messages.success(request, f"Global process '{process.title}' created successfully.")
            return redirect('processes:global_process_list')
    else:
        form = ProcessForm(is_global=True)
        formset = ProcessStageFormSet()

    return render(request, 'processes/global_process_form.html', {
        'form': form,
        'formset': formset,
        'action': 'Create',
    })


# Process Execution
@login_required
def execution_create(request, slug):
    """Create a process execution.

    New behavior (PSA enabled): every workflow run is attached to a freshly
    created native PSA ticket. The user picks a client org from a dropdown
    on the form; we create a Ticket for that org and link the execution via
    `native_psa_ticket=ticket`, then redirect to the ticket page where the
    embedded checklist lives.

    Legacy behavior (PSA disabled): keep the original free-floating
    execution flow so installs without PSA still work.
    """
    from core.models import Organization, SystemSetting

    org = get_request_organization(request)

    # v3.17.169 — when the user is in Global view (no current org), don't bail
    # out with "Organization context required". Instead let them pick the
    # organization to scope the workflow run. The PSA-enabled path already
    # asks for a `client_org_id` on the form; we honor that picked org as the
    # request-scoped one. For the legacy (PSA-disabled) path, we use the
    # `selected_org_id` field rendered by the org-picker block.
    needs_org_pick = False
    org_choices = None
    if not org:
        is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
        if request.user.is_superuser or is_staff:
            org_choices = Organization.objects.filter(is_active=True).order_by('name')
        else:
            from accounts.models import Membership
            org_ids = Membership.objects.filter(
                user=request.user, is_active=True
            ).values_list('organization_id', flat=True)
            org_choices = Organization.objects.filter(
                pk__in=org_ids, is_active=True
            ).order_by('name')
        if not org_choices.exists():
            messages.error(request,
                'You must be a member of at least one organization to launch workflows.')
            return redirect('accounts:organization_list')
        if request.method == 'POST':
            picked = (request.POST.get('selected_org_id')
                      or request.POST.get('client_org_id') or '').strip()
            if picked:
                try:
                    org = org_choices.get(pk=int(picked))
                except (Organization.DoesNotExist, ValueError, TypeError):
                    org = None
        needs_org_pick = org is None

    if needs_org_pick:
        # Render the form with an org picker; let the user pick on POST.
        process = get_object_or_404(
            Process.objects.filter(Q(is_global=True) | Q(organization__in=org_choices)),
            slug=slug
        )
        psa_enabled = bool(getattr(SystemSetting.get_settings(), 'psa_enabled', False))
        if request.method == 'POST':
            messages.error(request,
                'Please pick an organization to scope this workflow run.')
        return render(request, 'processes/execution_form.html', {
            'form': ProcessExecutionForm(),
            'process': process,
            'current_organization': None,
            'psa_enabled': psa_enabled,
            'client_orgs': org_choices,
            'org_choices': org_choices,
            'needs_org_pick': True,
        })

    process = get_object_or_404(
        Process.objects.filter(Q(organization=org) | Q(is_global=True)),
        slug=slug
    )

    psa_enabled = bool(getattr(SystemSetting.get_settings(), 'psa_enabled', False))
    client_orgs = Organization.objects.filter(is_active=True).order_by('name')

    if request.method == 'POST':
        form = ProcessExecutionForm(request.POST, organization=org)
        if form.is_valid():
            if psa_enabled:
                # ----------------- New path: create a PSA ticket -----------------
                from psa.models import (
                    Queue,
                    Ticket,
                    TicketPriority,
                    TicketStatus,
                    TicketType,
                )
                from accounts.models import Membership
                try:
                    from psa.sla import apply_due_dates
                except Exception:
                    apply_due_dates = None  # SLA module optional; ticket still saves.

                client_org_id = (request.POST.get('client_org_id') or '').strip()
                if not client_org_id:
                    messages.error(request, 'Please pick a client for this workflow.')
                    return render(request, 'processes/execution_form.html', {
                        'form': form,
                        'process': process,
                        'current_organization': org,
                        'psa_enabled': psa_enabled,
                        'client_orgs': client_orgs,
                    })
                try:
                    client_org = client_orgs.get(pk=client_org_id)
                except Organization.DoesNotExist:
                    messages.error(request, 'That client is not available.')
                    return render(request, 'processes/execution_form.html', {
                        'form': form,
                        'process': process,
                        'current_organization': org,
                        'psa_enabled': psa_enabled,
                        'client_orgs': client_orgs,
                    })

                queue = Queue.objects.filter(is_active=True).first()
                status_obj = TicketStatus.objects.filter(slug='new').first()
                priority = TicketPriority.objects.first()
                ticket_type = TicketType.objects.first()
                if not (queue and status_obj and priority and ticket_type):
                    messages.error(
                        request,
                        'PSA is not fully configured (missing default queue/status/priority/type). '
                        'Set up PSA defaults before launching workflows as tickets.'
                    )
                    return render(request, 'processes/execution_form.html', {
                        'form': form,
                        'process': process,
                        'current_organization': org,
                        'psa_enabled': psa_enabled,
                        'client_orgs': client_orgs,
                    })

                user_has_membership = Membership.objects.filter(
                    user=request.user, organization=client_org, is_active=True
                ).exists()
                notes = (form.cleaned_data.get('notes') or '').strip()

                # v3.17.129 — admins can pick a different tech to own the
                # execution (and the ticket it spawns). Falls back to the
                # launcher when the user isn't allowed to reassign.
                from psa.views import _can_assign, _eligible_assignees
                from django.contrib.auth.models import User as _User
                assignee = request.user
                posted = (request.POST.get('assigned_to') or '').strip()
                if posted and _can_assign(request, client_org):
                    try:
                        cand = _User.objects.get(pk=int(posted), is_active=True)
                        eligible_ids = set(
                            _eligible_assignees(client_org).values_list('id', flat=True)
                        )
                        if cand.id in eligible_ids:
                            assignee = cand
                    except (_User.DoesNotExist, ValueError, TypeError):
                        pass

                ticket = Ticket.objects.create(
                    organization=client_org,
                    subject=f"Workflow: {process.title}",
                    description=notes,
                    queue=queue,
                    status=status_obj,
                    priority=priority,
                    ticket_type=ticket_type,
                    source='manual',
                    created_by=request.user,
                    updated_by=request.user,
                    assigned_to=assignee if (user_has_membership or assignee != request.user) else None,
                )
                if apply_due_dates:
                    try:
                        apply_due_dates(ticket)
                    except Exception:
                        logger.exception("apply_due_dates failed for new workflow ticket")

                execution = form.save(commit=False)
                execution.process = process
                execution.organization = client_org
                execution.assigned_to = assignee
                execution.started_by = request.user
                execution.started_at = timezone.now()
                execution.status = 'in_progress'
                execution.native_psa_ticket = ticket
                execution.save()

                # Create stage completion records
                for stage in process.stages.all():
                    ProcessStageCompletion.objects.create(
                        execution=execution,
                        stage=stage,
                        is_completed=False
                    )

                # Log execution creation
                ProcessExecutionAuditLog.log_action(
                    execution=execution,
                    action_type='execution_created',
                    user=request.user,
                    description=(
                        f"{request.user.username} launched workflow '{process.title}' "
                        f"on ticket {ticket.ticket_number}"
                    ),
                    request=request
                )

                messages.success(
                    request,
                    f"Created ticket {ticket.ticket_number} with workflow {process.title}"
                )
                return redirect('psa:ticket_detail', ticket_number=ticket.ticket_number)

            # ------------------- Legacy path: PSA disabled -------------------
            execution = form.save(commit=False)
            execution.process = process
            execution.organization = org
            execution.assigned_to = request.user  # Automatically assign to launcher
            execution.started_by = request.user
            execution.started_at = timezone.now()
            execution.status = 'in_progress'
            execution.save()

            # Create stage completion records
            for stage in process.stages.all():
                ProcessStageCompletion.objects.create(
                    execution=execution,
                    stage=stage,
                    is_completed=False
                )

            # Log execution creation
            ProcessExecutionAuditLog.log_action(
                execution=execution,
                action_type='execution_created',
                user=request.user,
                description=f"{request.user.username} launched workflow '{process.title}'",
                request=request
            )

            messages.success(request, f"Started execution of '{process.title}'.")
            return redirect('processes:execution_detail', pk=execution.pk)
    else:
        form = ProcessExecutionForm(organization=org)

    # v3.17.129 — surface an "Assign to" picker for admins. We don't know
    # which client they'll pick yet, so offer the union of techs across all
    # clients they can act on (server re-validates against the chosen org).
    from psa.views import _can_assign, _eligible_assignees
    can_assign = (
        request.user.is_superuser
        or getattr(request, 'is_staff_user', False)
        or any(_can_assign(request, c) for c in client_orgs)
    )
    eligible_assignees = []
    if can_assign:
        from django.contrib.auth.models import User as _User
        from django.db.models import Q as _Q
        client_ids = list(client_orgs.values_list('id', flat=True))
        eligible_assignees = list(
            _User.objects.filter(is_active=True)
            .filter(
                _Q(is_staff=True) | _Q(is_superuser=True)
                | _Q(memberships__organization_id__in=client_ids,
                     memberships__is_active=True)
            )
            .distinct()
            .order_by('username')
        )

    return render(request, 'processes/execution_form.html', {
        'form': form,
        'process': process,
        'current_organization': org,
        'psa_enabled': psa_enabled,
        'client_orgs': client_orgs,
        'can_assign': can_assign,
        'eligible_assignees': eligible_assignees,
    })


@login_required
def execution_list(request):
    """List all workflow executions for the organization"""
    org = get_request_organization(request)

    # Allow superusers/staff to view all executions in global view
    if not org:
        if request.user.is_superuser or request.is_staff_user:
            executions = ProcessExecution.objects.all().select_related(
                'process', 'assigned_to', 'started_by', 'organization'
            ).prefetch_related(
                'stage_completions'
            ).order_by('-created_at')
        else:
            # v3.17.169 — clearer message + still redirect (this is a list
            # endpoint with no form to embed a picker into).
            messages.error(request,
                'Switch to a specific organization first to view its workflow executions.')
            return redirect('accounts:organization_list')
    else:
        # Get all executions for this org
        executions = ProcessExecution.objects.filter(
            organization=org
        ).select_related(
            'process', 'assigned_to', 'started_by'
        ).prefetch_related(
            'stage_completions'
        ).order_by('-created_at')

    # Filter by status if requested
    status_filter = request.GET.get('status')
    if status_filter:
        executions = executions.filter(status=status_filter)

    # Filter by user if requested
    user_filter = request.GET.get('user')
    if user_filter:
        executions = executions.filter(assigned_to__id=user_filter)

    # Filter by process if requested
    process_filter = request.GET.get('process')
    if process_filter:
        executions = executions.filter(process__id=process_filter)

    # Get unique processes for filter dropdown
    if org:
        processes = Process.objects.filter(
            Q(organization=org) | Q(is_global=True)
        ).order_by('title')
    else:
        # Global view - show all processes
        processes = Process.objects.all().order_by('title')

    # Get unique users for filter dropdown
    from django.contrib.auth.models import User
    if org:
        users = User.objects.filter(
            memberships__organization=org,
            memberships__is_active=True
        ).distinct().order_by('username')
    else:
        # Global view - show all users
        users = User.objects.all().order_by('username')

    return render(request, 'processes/execution_list.html', {
        'executions': executions,
        'processes': processes,
        'users': users,
        'status_filter': status_filter,
        'user_filter': user_filter,
        'process_filter': process_filter,
        'current_organization': org,
    })


@login_required
def execution_detail(request, pk):
    """View execution with stage completion tracking.

    If this execution is attached to a native PSA ticket, the canonical
    home for the checklist is the ticket detail page. Bounce there so users
    don't see two slightly-different views of the same workflow run.
    Superusers can still hit the legacy page with `?legacy=1` for debugging
    standalone executions.
    """
    org = get_request_organization(request)

    # Allow superusers/staff to view any execution in global view
    if org:
        execution = get_object_or_404(ProcessExecution, pk=pk, organization=org)
    elif request.user.is_superuser or request.is_staff_user:
        execution = get_object_or_404(ProcessExecution, pk=pk)
    else:
        execution = get_object_or_404(ProcessExecution, pk=pk, organization=org)

    # Redirect to the PSA ticket page where the embedded checklist now lives.
    if execution.native_psa_ticket_id and not (
        request.user.is_superuser and request.GET.get('legacy')
    ):
        return redirect(
            'psa:ticket_detail',
            ticket_number=execution.native_psa_ticket.ticket_number,
        )

    # Get stage completions
    completions = execution.stage_completions.all().select_related('stage')

    # Calculate counts
    completed_count = completions.filter(is_completed=True).count()
    incomplete_count = completions.filter(is_completed=False).count()

    return render(request, 'processes/execution_detail.html', {
        'execution': execution,
        'completions': completions,
        'completed_count': completed_count,
        'incomplete_count': incomplete_count,
        'current_organization': org,
    })


@login_required
def execution_audit_log(request, pk):
    """View audit log for a specific execution"""
    org = get_request_organization(request)

    # Allow superusers/staff to view any execution in global view
    if org:
        execution = get_object_or_404(ProcessExecution, pk=pk, organization=org)
    elif request.user.is_superuser or request.is_staff_user:
        execution = get_object_or_404(ProcessExecution, pk=pk)
    else:
        execution = get_object_or_404(ProcessExecution, pk=pk, organization=org)

    # Get all audit logs for this execution
    audit_logs = execution.audit_logs.select_related('user', 'stage').all()

    # Group by date for better visualization
    logs_by_date = {}
    for log in audit_logs:
        date_key = log.created_at.date()
        if date_key not in logs_by_date:
            logs_by_date[date_key] = []
        logs_by_date[date_key].append(log)

    return render(request, 'processes/execution_audit_log.html', {
        'execution': execution,
        'audit_logs': audit_logs,
        'logs_by_date': sorted(logs_by_date.items(), reverse=True),
        'current_organization': org,
    })


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def execution_delete(request, pk):
    """Delete a workflow execution (admin only)"""
    org = get_request_organization(request)

    # Allow superusers to delete any execution in global view
    if org:
        execution = get_object_or_404(ProcessExecution, pk=pk, organization=org)
    else:
        execution = get_object_or_404(ProcessExecution, pk=pk)

    # Store execution details for message
    process_title = execution.process.title
    assigned_to = execution.assigned_to.username if execution.assigned_to else "Unassigned"

    # Delete the execution (cascade will delete completions and audit logs)
    execution.delete()

    messages.success(
        request,
        f'Workflow execution deleted: {process_title} (assigned to {assigned_to})'
    )
    logger.info(f"Admin {request.user.username} deleted execution #{pk} for process '{process_title}'")

    # Redirect to execution list
    return redirect('processes:execution_list')


@login_required
def stage_complete(request, pk):
    """Mark a stage as complete (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    completion = get_object_or_404(ProcessStageCompletion, pk=pk)

    # Check permissions
    org = get_request_organization(request)
    if completion.execution.organization != org:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    # Store old state for audit
    was_completed = completion.is_completed
    psa_note_error = None

    # Update completion
    completion.is_completed = True
    completion.completed_by = request.user
    completion.completed_at = timezone.now()
    completion.save()

    # Log the stage completion
    ProcessExecutionAuditLog.log_action(
        execution=completion.execution,
        action_type='stage_completed',
        user=request.user,
        description=f"{request.user.username} completed stage '{completion.stage.title}'",
        stage=completion.stage,
        old_value={'is_completed': was_completed},
        new_value={'is_completed': True, 'completed_at': str(completion.completed_at)},
        request=request
    )

    # Check if all stages complete -> mark execution complete
    if completion.execution.stage_completions.filter(is_completed=False).count() == 0:
        old_status = completion.execution.status
        completion.execution.status = 'completed'
        completion.execution.completed_at = timezone.now()
        completion.execution.save()

        # Log execution completion
        ProcessExecutionAuditLog.log_action(
            execution=completion.execution,
            action_type='execution_completed',
            user=request.user,
            description=f"{request.user.username} completed the entire execution",
            old_value={'status': old_status},
            new_value={'status': 'completed'},
            request=request
        )

        # Update PSA ticket if linked
        if completion.execution.psa_ticket:
            try:
                # Generate completion summary
                summary = f"Workflow '{completion.execution.process.title}' completed by {request.user.username}.\n\n"
                summary += "Completed steps:\n"
                for stage_completion in completion.execution.stage_completions.filter(is_completed=True):
                    completed_at = stage_completion.completed_at.strftime('%Y-%m-%d %H:%M')
                    completed_by = stage_completion.completed_by.username if stage_completion.completed_by else 'Unknown'
                    summary += f"- {stage_completion.stage.title} (completed by {completed_by} at {completed_at})\n"

                # Post to PSA ticket
                from integrations.psa_manager import PSAManager
                psa_manager = PSAManager()
                result = psa_manager.add_ticket_note(
                    ticket=completion.execution.psa_ticket,
                    note=summary,
                    internal=completion.execution.psa_note_internal
                )

                # Log what actually happened. Recording "updated PSA ticket X"
                # without looking at the result left the audit trail asserting a
                # note had reached the PSA whether or not one ever did.
                psa_number = completion.execution.psa_ticket.ticket_number
                if result:
                    description = (
                        f"{request.user.username} completed execution and updated "
                        f"PSA ticket {psa_number}"
                    )
                else:
                    description = (
                        f"{request.user.username} completed execution; the note for "
                        f"PSA ticket {psa_number} was NOT posted ({result.detail})"
                    )
                    logger.error(f"PSA note not posted: {result.detail}")
                    psa_note_error = result.detail

                ProcessExecutionAuditLog.log_action(
                    execution=completion.execution,
                    action_type='execution_completed',
                    user=request.user,
                    description=description,
                    new_value={'psa_note_posted': bool(result), 'psa_ticket': psa_number},
                    request=request
                )
            except Exception as e:
                logger.error(f"Failed to update PSA ticket: {e}")
                psa_note_error = str(e)
                # Don't fail the execution if PSA update fails

    response = {
        'success': True,
        'completion_percentage': completion.execution.completion_percentage
    }
    # A workflow that finishes without its PSA note has still finished, so the
    # stage completion stands — but the tech is told, instead of finding out
    # when the customer asks why the ticket went quiet.
    if psa_note_error:
        response['psa_note_posted'] = False
        response['psa_note_error'] = psa_note_error
    return JsonResponse(response)


@login_required
def stage_uncomplete(request, pk):
    """Mark a stage as incomplete (AJAX) - for unchecking"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    completion = get_object_or_404(ProcessStageCompletion, pk=pk)

    # Check permissions
    org = get_request_organization(request)
    if completion.execution.organization != org:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    # Only allow uncompleting if execution is still in progress
    if completion.execution.status not in ['in_progress', 'not_started']:
        return JsonResponse({'error': 'Cannot modify completed execution'}, status=400)

    # Store for audit
    was_completed = completion.is_completed
    old_completed_by = completion.completed_by.username if completion.completed_by else None

    # Update
    completion.is_completed = False
    completion.completed_by = None
    completion.completed_at = None
    completion.save()

    # Log the uncomplete action
    ProcessExecutionAuditLog.log_action(
        execution=completion.execution,
        action_type='stage_uncompleted',
        user=request.user,
        description=f"{request.user.username} marked stage '{completion.stage.title}' as incomplete",
        stage=completion.stage,
        old_value={'is_completed': was_completed, 'completed_by': old_completed_by},
        new_value={'is_completed': False},
        request=request
    )

    return JsonResponse({
        'success': True,
        'completion_percentage': completion.execution.completion_percentage
    })


@login_required
def stage_reorder(request, slug):
    """Reorder stages via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    org = get_request_organization(request)
    process = get_object_or_404(Process, slug=slug, organization=org)

    import json
    data = json.loads(request.body)
    stage_orders = data.get('stages', [])

    for item in stage_orders:
        stage_id = item['id']
        new_order = item['order']
        ProcessStage.objects.filter(id=stage_id, process=process).update(order=new_order)

    return JsonResponse({'success': True})


@login_required
@require_http_methods(['POST'])
def process_clone_template(request, slug):
    """
    Phase 38: clone an `is_template=True` Process — including its stages
    — into a new non-template Process for the user's current org.
    """
    from django.utils.text import slugify
    org = get_request_organization(request)
    src = get_object_or_404(
        Process,
        Q(slug=slug) & (Q(organization=org) | Q(is_global=True)),
    )
    if not src.is_template:
        messages.error(request, 'Only templates can be cloned. Use the New Workflow form for ad-hoc runbooks.')
        return redirect('processes:process_detail', slug=src.slug)
    if org is None:
        messages.error(request, 'Pick an organization context first.')
        return redirect('processes:process_list')

    today = timezone.now().date()
    new_title = f'[{today.isoformat()}] {src.title}'
    base_slug = slugify(new_title)[:240] or 'runbook-run'
    candidate_slug = base_slug
    n = 2
    while Process.objects.filter(organization=org, slug=candidate_slug).exists():
        candidate_slug = f'{base_slug}-{n}'
        n += 1

    clone = Process.objects.create(
        organization=org,
        title=new_title[:255],
        slug=candidate_slug,
        description=src.description,
        is_template=False,
        is_published=True,
        is_archived=False,
        is_global=False,
        category=src.category,
        linked_diagram=src.linked_diagram,
        created_by=request.user,
        last_modified_by=request.user,
    )
    for stage in src.stages.all().order_by('order'):
        ProcessStage.objects.create(
            process=clone,
            order=stage.order,
            title=stage.title,
            description=stage.description,
            linked_document=stage.linked_document,
            linked_password=stage.linked_password,
            linked_secure_note=stage.linked_secure_note,
            linked_asset=stage.linked_asset,
            requires_confirmation=stage.requires_confirmation,
            estimated_duration_minutes=stage.estimated_duration_minutes,
        )
    messages.success(request, f'Runbook "{clone.title}" created from template "{src.title}".')
    return redirect('processes:process_detail', slug=clone.slug)


@login_required
@require_http_methods(['POST'])
def stage_spawn_ticket(request, execution_pk, stage_pk):
    """
    Phase 38: create a PSA Ticket from a runbook stage. Subject = stage
    title, description = stage description, org = execution's org. The
    created ticket is recorded on `ProcessStageCompletion.spawned_ticket`
    so the runbook UI can link back to it. Idempotent.
    """
    from psa.models import Ticket, Queue, TicketPriority, TicketStatus, TicketType
    org = get_request_organization(request)
    qs = ProcessExecution.objects.all()
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        qs = qs.none()
    execution = get_object_or_404(qs, pk=execution_pk)
    stage = get_object_or_404(ProcessStage, pk=stage_pk, process=execution.process)

    completion, _ = ProcessStageCompletion.objects.get_or_create(
        execution=execution, stage=stage,
    )
    if completion.spawned_ticket_id:
        messages.info(request, f'Ticket {completion.spawned_ticket.ticket_number} already linked to this stage.')
        return redirect('processes:execution_detail', pk=execution.pk)

    queue = Queue.objects.filter(is_active=True).first()
    priority = TicketPriority.objects.first()
    ttype = TicketType.objects.first()
    status = TicketStatus.objects.filter(slug='new').first()
    if not (queue and priority and ttype and status):
        messages.error(request, 'PSA defaults missing — cannot spawn ticket. Run psa_seed_defaults.')
        return redirect('processes:execution_detail', pk=execution.pk)

    ticket = Ticket.objects.create(
        organization=execution.organization,
        subject=f'[Runbook] {stage.title}'[:200],
        description=stage.description or f'Spawned from runbook stage "{stage.title}" in execution #{execution.pk}.',
        queue=queue, priority=priority, ticket_type=ttype, status=status,
        source='manual',
        assigned_to=execution.assigned_to,
        created_by=request.user,
    )
    completion.spawned_ticket = ticket
    completion.save(update_fields=['spawned_ticket'])
    messages.success(request, f'Ticket {ticket.ticket_number} created from stage "{stage.title}".')
    return redirect('processes:execution_detail', pk=execution.pk)



@login_required
def runbook_dashboard(request, org_id=None):
    """
    Phase 38 v2 (v3.17.227): per-client runbook completion dashboard.

    Lists every active ProcessExecution scoped to the requested org (or
    the user's current org context when org_id is omitted), grouped by
    runbook category and rendered with each execution's
    completion_percentage. The org-level rollup at the top sums covered
    vs total stages so a tech can see "OrgA is 65% through their
    onboarding runbooks" at a glance.

    URL:
      /processes/dashboard/             → user's current org
      /processes/dashboard/<org_id>/    → explicit org (staff/superuser)
    """
    from core.models import Organization
    if org_id is not None:
        org = get_object_or_404(Organization, pk=org_id)
        if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
            if not request.user.memberships.filter(
                organization=org, is_active=True,
            ).exists():
                from django.http import Http404
                raise Http404('Organization not visible')
    else:
        org = get_request_organization(request)
        if org is None:
            messages.info(request, 'Pick an organization context to see its runbook dashboard.')
            return redirect('processes:execution_list')

    # All non-cancelled executions for the org; group by category of the
    # underlying Process. Cancelled / failed are excluded — they're noise
    # for "what's in flight" view but visible via execution_list.
    qs = (ProcessExecution.objects
          .filter(organization=org)
          .exclude(status__in=['cancelled', 'failed'])
          .select_related('process', 'assigned_to')
          .order_by('process__category', '-created_at'))

    groups = {}
    total_stages = 0
    completed_stages = 0
    for ex in qs:
        cat = ex.process.category
        groups.setdefault(cat, []).append(ex)
        n_stages = ex.process.stages.count()
        n_done = ex.stage_completions.filter(is_completed=True).count()
        total_stages += n_stages
        completed_stages += n_done

    overall_pct = round(100 * completed_stages / total_stages, 1) if total_stages else 0

    # Render category labels using model choices for readability.
    cat_choices = dict(Process.CATEGORY_CHOICES)
    rendered_groups = []
    for cat, executions in sorted(groups.items()):
        rendered_groups.append({
            'category_key': cat,
            'category_label': cat_choices.get(cat, cat.title()),
            'executions': executions,
            'count': len(executions),
        })

    return render(request, 'processes/runbook_dashboard.html', {
        'organization': org,
        'groups': rendered_groups,
        'total_executions': qs.count(),
        'overall_pct': overall_pct,
        'total_stages': total_stages,
        'completed_stages': completed_stages,
    })
