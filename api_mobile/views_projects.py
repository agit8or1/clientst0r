"""
Mobile API project endpoints (v3.17.558).

Phase 35 built projects, budgets, profitability, timelines and billing on the
web. A technician in a van needs a much smaller slice of that: what am I on,
what is left to do, and mark this done. Profitability and billing are
deliberately absent — margin is not a number to hand somebody standing in a
client's server room, and nothing here can raise an invoice.
"""
from __future__ import annotations

from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permission_utils import user_has_perm

from .scoping import accessible_org_ids


def _serialize_project(project, *, detail=False):
    out = {
        'id': project.id,
        'name': project.name,
        'status': project.status,
        'organization_id': project.organization_id,
        'organization_name': (project.organization.name
                              if project.organization_id else None),
        'start_date': project.start_date.isoformat() if project.start_date else None,
        'due_date': project.due_date.isoformat() if project.due_date else None,
        'owner_name': _user_label(project.owner) if project.owner_id else None,
        'task_count': project.tasks.count(),
        'open_task_count': project.tasks.exclude(status='done').count(),
    }
    if detail:
        budget = project.budget_summary()
        out.update({
            'description': project.description,
            'is_billable': project.is_billable,
            'estimated_hours': (str(project.estimated_hours)
                                if project.estimated_hours is not None else None),
            # Hours only. A tech should see whether the job is running over,
            # which is a scheduling fact. What it earns is not their call and
            # not their conversation with the client.
            'budget': {
                'state': budget['state'],
                'hours_actual': str(budget['hours_actual']),
                'hours_budget': (str(budget['hours_budget'])
                                 if budget['hours_budget'] is not None else None),
                'hours_percent': budget['hours_percent'],
            },
        })
    return out


def _user_label(user):
    full = (user.get_full_name() or '').strip()
    return full or user.username


def _serialize_task(task):
    return {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'is_milestone': task.is_milestone,
        'start_date': task.start_date.isoformat() if task.start_date else None,
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'estimated_hours': (str(task.estimated_hours)
                            if task.estimated_hours is not None else None),
        'assigned_to_id': task.assigned_to_id,
        'assigned_to_name': (_user_label(task.assigned_to)
                             if task.assigned_to_id else None),
        'ticket_number': (task.related_ticket.ticket_number
                          if task.related_ticket_id else None),
        'ticket_id': task.related_ticket_id,
        # Phase 35.5 — a task waiting on something else is worth flagging here,
        # because the whole point of the mobile view is deciding what to do next.
        'is_blocked': task.is_blocked,
        'blocked_by': [d.title for d in task.blocking_dependencies],
    }


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def project_list_view(request):
    """
    GET /api/mobile/v1/projects/?status=&organization_id=&mine=true

    `mine=true` narrows to projects the caller owns or has a task on — which is
    the default question a tech is asking, but not the default answer, because
    a project with nothing assigned yet would then be invisible.
    """
    from psa.models import Project

    org_ids = accessible_org_ids(request.user)
    qs = (Project.objects.filter(organization_id__in=org_ids)
          .select_related('organization', 'owner')
          .prefetch_related('tasks'))

    status = (request.query_params.get('status') or '').strip()
    if status == 'open':
        # "Open" on mobile means work that is still live, not a status slug.
        qs = qs.exclude(status__in=['completed', 'cancelled'])
    elif status:
        qs = qs.filter(status=status)

    organization_id = request.query_params.get('organization_id')
    if organization_id:
        try:
            oid = int(organization_id)
            qs = qs.filter(organization_id=oid) if oid in org_ids else qs.none()
        except ValueError:
            pass

    if request.query_params.get('mine') == 'true':
        from django.db.models import Q
        qs = qs.filter(
            Q(owner=request.user) | Q(tasks__assigned_to=request.user)
        ).distinct()

    qs = qs.order_by('due_date', 'name')

    try:
        page = max(int(request.query_params.get('page', 1)), 1)
    except ValueError:
        page = 1
    page_size = 50
    start = (page - 1) * page_size
    total = qs.count()

    return Response({
        'count': total,
        'page': page,
        'page_size': page_size,
        'results': [_serialize_project(p) for p in qs[start:start + page_size]],
    })


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def project_detail_view(request, pk: int):
    """GET /api/mobile/v1/projects/<id>/ — project plus its tasks."""
    from psa.models import Project

    org_ids = accessible_org_ids(request.user)
    try:
        project = (Project.objects
                   .select_related('organization', 'owner')
                   .get(pk=pk, organization_id__in=org_ids))
    except Project.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    tasks = (project.tasks
             .select_related('assigned_to', 'related_ticket')
             .prefetch_related('depends_on')
             .order_by('sort_order', 'id'))

    payload = _serialize_project(project, detail=True)
    payload['tasks'] = [_serialize_task(t) for t in tasks]
    return Response(payload)


@api_view(['PATCH'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def project_task_view(request, pk: int):
    """
    PATCH /api/mobile/v1/project-tasks/<id>/   body: {status}

    Status only. Retitling, rescheduling and reassigning a plan line are
    planning decisions that belong on the web, where the timeline and the
    dependencies are visible; ticking one off is the thing you do standing in
    front of the work.
    """
    from psa.models import ProjectTask

    org_ids = accessible_org_ids(request.user)
    try:
        task = (ProjectTask.objects
                .select_related('project', 'assigned_to', 'related_ticket')
                .prefetch_related('depends_on')
                .get(pk=pk, project__organization_id__in=org_ids))
    except ProjectTask.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    if not user_has_perm(request.user, 'tickets_edit'):
        return Response(
            {'detail': "You don't have permission to update project work."},
            status=403)

    status = (request.data or {}).get('status')
    valid = dict(ProjectTask.STATUS_CHOICES)
    if status not in valid:
        return Response(
            {'detail': f'status must be one of: {", ".join(sorted(valid))}'},
            status=400)

    # A blocked task can still be marked done — the dependency may have been
    # finished by somebody who has not updated it yet, and refusing would leave
    # a tech unable to record work they have actually done.
    task.status = status
    if status == 'done' and task.completed_at is None:
        from django.utils import timezone
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'completed_at', 'updated_at'])
    else:
        task.save(update_fields=['status', 'updated_at'])

    return Response(_serialize_task(task))
