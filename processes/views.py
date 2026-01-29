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
        # No org and not in global view - need org context
        messages.error(request, 'Organization context required.')
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
    })


@login_required
def process_detail(request, slug):
    """View process details with all stages"""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

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

    # Get user's active executions for this process
    my_executions = ProcessExecution.objects.filter(
        process=process,
        organization=org,
        assigned_to=request.user,
        status__in=['not_started', 'in_progress']
    )

    return render(request, 'processes/process_detail.html', {
        'process': process,
        'stages': stages,
        'current_organization': org,
        'my_executions': my_executions,
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
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

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
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

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
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

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
    """Create a process execution"""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

    process = get_object_or_404(
        Process.objects.filter(Q(organization=org) | Q(is_global=True)),
        slug=slug
    )

    if request.method == 'POST':
        form = ProcessExecutionForm(request.POST, organization=org)
        if form.is_valid():
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

    return render(request, 'processes/execution_form.html', {
        'form': form,
        'process': process,
        'current_organization': org,
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
            messages.error(request, 'Organization context required.')
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
    """View execution with stage completion tracking"""
    org = get_request_organization(request)

    # Allow superusers/staff to view any execution in global view
    if org:
        execution = get_object_or_404(ProcessExecution, pk=pk, organization=org)
    elif request.user.is_superuser or request.is_staff_user:
        execution = get_object_or_404(ProcessExecution, pk=pk)
    else:
        execution = get_object_or_404(ProcessExecution, pk=pk, organization=org)

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
                psa_manager.add_ticket_note(
                    ticket=completion.execution.psa_ticket,
                    note=summary,
                    internal=completion.execution.psa_note_internal
                )

                # Log the PSA update in audit
                ProcessExecutionAuditLog.log_action(
                    execution=completion.execution,
                    action_type='execution_completed',
                    user=request.user,
                    description=f"{request.user.username} completed execution and updated PSA ticket {completion.execution.psa_ticket.ticket_number}",
                    request=request
                )
            except Exception as e:
                logger.error(f"Failed to update PSA ticket: {e}")
                # Don't fail the execution if PSA update fails

    return JsonResponse({
        'success': True,
        'completion_percentage': completion.execution.completion_percentage
    })


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
