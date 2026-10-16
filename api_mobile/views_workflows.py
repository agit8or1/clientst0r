"""
Mobile API workflow (process) endpoints (v3.17.455).

Wraps the `processes` app — internally the runbook engine is called
"processes" but the mobile UX surfaces them as "workflows" since that's
the term users recognize. List published processes available to the
user's accessible orgs (including globals), start an execution, mark
stage completion.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import status as drf_status
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .scoping import accessible_org_ids


def _serialize_process(p, *, with_stages: bool = False) -> dict:
    out = {
        'id': p.id,
        'title': p.title,
        'slug': p.slug,
        'description': p.description,
        'category': p.category,
        'is_global': p.is_global,
        'organization_id': p.organization_id,
        'organization_name': p.organization.name if p.organization_id else None,
        'stage_count': p.stages.count(),
    }
    if with_stages:
        out['stages'] = [
            {
                'id': s.id,
                'order': s.order,
                'title': s.title,
                'description': s.description,
                'requires_confirmation': s.requires_confirmation,
                'estimated_duration_minutes': s.estimated_duration_minutes,
                'linked_document_id': s.linked_document_id,
                'linked_password_id': s.linked_password_id,
                'linked_asset_id': s.linked_asset_id,
            }
            for s in p.stages.all().order_by('order')
        ]
    return out


def _serialize_execution(e, *, with_stages: bool = False) -> dict:
    out = {
        'id': e.id,
        'process_id': e.process_id,
        'process_title': e.process.title if e.process_id else None,
        'organization_id': e.organization_id,
        'organization_name': e.organization.name if e.organization_id else None,
        'assigned_to_id': e.assigned_to_id,
        'started_by_id': e.started_by_id,
        'status': e.status,
        'started_at': e.started_at.isoformat() if e.started_at else None,
        'completed_at': e.completed_at.isoformat() if e.completed_at else None,
        'due_date': e.due_date.isoformat() if e.due_date else None,
        'notes': e.notes,
    }
    if with_stages:
        completions = {c.stage_id: c for c in e.stage_completions.all()}
        out['stages'] = []
        for s in e.process.stages.all().order_by('order'):
            c = completions.get(s.id)
            out['stages'].append({
                'stage_id': s.id,
                'order': s.order,
                'title': s.title,
                'description': s.description,
                'requires_confirmation': s.requires_confirmation,
                'is_completed': bool(c and c.is_completed),
                'completed_at': c.completed_at.isoformat() if c and c.completed_at else None,
                'completed_by_id': c.completed_by_id if c else None,
                'notes': c.notes if c else '',
                # v3.17.459: surface linked-entity ids so the mobile UI can
                # deep-link to /vault/<id> / /assets/<id> / /kb/<id>.
                'linked_password_id': s.linked_password_id,
                'linked_asset_id': s.linked_asset_id,
                'linked_document_id': s.linked_document_id,
            })
    return out


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def workflow_list_view(request):
    """
    GET /api/mobile/v1/workflows/?search=&category=&organization_id=

    Lists published, non-archived processes the user can run — anything
    in their accessible orgs plus globals.
    """
    from processes.models import Process

    org_ids = list(accessible_org_ids(request.user))
    qs = (Process.objects
          .filter(is_published=True, is_archived=False)
          .filter(Q(organization_id__in=org_ids) | Q(is_global=True))
          .select_related('organization'))

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))

    category = request.query_params.get('category')
    if category:
        qs = qs.filter(category=category)

    org_filter = request.query_params.get('organization_id')
    if org_filter:
        try:
            oid = int(org_filter)
            if oid in org_ids:
                qs = qs.filter(organization_id=oid)
        except ValueError:
            pass

    qs = qs.order_by('title')[:200]
    return Response({
        'count': len(qs),
        'results': [_serialize_process(p) for p in qs],
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def workflow_detail_view(request, pk: int):
    """GET /api/mobile/v1/workflows/<id>/ — process with full stage list."""
    from processes.models import Process
    org_ids = list(accessible_org_ids(request.user))
    try:
        p = Process.objects.select_related('organization').get(
            Q(pk=pk),
            Q(is_published=True, is_archived=False),
            Q(organization_id__in=org_ids) | Q(is_global=True),
        )
    except Process.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    return Response(_serialize_process(p, with_stages=True))


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def workflow_start_view(request, pk: int):
    """
    POST /api/mobile/v1/workflows/<id>/start/

    Body: `{organization_id?, notes?, due_date?}`. Creates a
    `ProcessExecution` assigned to the caller, status=in_progress.
    `organization_id` defaults to the process's org for non-global
    processes, or must be supplied (and accessible) for globals.
    """
    from processes.models import Process, ProcessExecution

    org_ids = list(accessible_org_ids(request.user))
    try:
        p = Process.objects.get(
            Q(pk=pk),
            Q(is_published=True, is_archived=False),
            Q(organization_id__in=org_ids) | Q(is_global=True),
        )
    except Process.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    data = request.data or {}

    # Resolve target org
    target_org_id = data.get('organization_id')
    if target_org_id is None:
        if p.is_global:
            return Response(
                {'detail': 'organization_id required for global workflows'},
                status=400,
            )
        target_org_id = p.organization_id
    else:
        try:
            target_org_id = int(target_org_id)
        except (TypeError, ValueError):
            return Response({'detail': 'invalid organization_id'}, status=400)
        if target_org_id not in org_ids:
            return Response({'detail': 'organization not accessible'}, status=403)

    exe = ProcessExecution.objects.create(
        process=p,
        organization_id=target_org_id,
        assigned_to=request.user,
        started_by=request.user,
        status='in_progress',
        started_at=timezone.now(),
        notes=(data.get('notes') or '')[:5000],
    )
    return Response(_serialize_execution(exe, with_stages=True),
                    status=drf_status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def my_executions_view(request):
    """
    GET /api/mobile/v1/workflows/executions/?status=

    My in-progress + recent executions.
    """
    from processes.models import ProcessExecution
    qs = (ProcessExecution.objects
          .filter(assigned_to=request.user)
          .select_related('process', 'organization'))
    status = request.query_params.get('status')
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by('-started_at', '-created_at')[:50]
    return Response({
        'count': len(qs),
        'results': [_serialize_execution(e) for e in qs],
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def execution_detail_view(request, pk: int):
    """GET /api/mobile/v1/workflows/executions/<id>/ — with all stage states."""
    from processes.models import ProcessExecution
    try:
        e = ProcessExecution.objects.select_related('process', 'organization').get(
            pk=pk, assigned_to=request.user,
        )
    except ProcessExecution.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    return Response(_serialize_execution(e, with_stages=True))


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def execution_complete_stage_view(request, pk: int, stage_id: int):
    """
    POST /api/mobile/v1/workflows/executions/<exec_id>/stages/<stage_id>/complete/

    Body: `{notes?}`. Idempotent — calling twice is fine.
    Auto-completes the execution when all required stages are done.
    """
    from processes.models import (
        ProcessExecution, ProcessStage, ProcessStageCompletion,
    )

    try:
        exe = ProcessExecution.objects.get(pk=pk, assigned_to=request.user)
    except ProcessExecution.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    try:
        stage = ProcessStage.objects.get(pk=stage_id, process=exe.process)
    except ProcessStage.DoesNotExist:
        return Response({'detail': 'Stage not part of this workflow'}, status=400)

    notes = (request.data.get('notes') or '')[:2000] if request.data else ''
    completion, _ = ProcessStageCompletion.objects.update_or_create(
        execution=exe, stage=stage,
        defaults={
            'is_completed': True,
            'completed_by': request.user,
            'completed_at': timezone.now(),
            'notes': notes,
        },
    )

    # Auto-finish the execution when every stage has a completion row
    total_stages = exe.process.stages.count()
    done_stages = ProcessStageCompletion.objects.filter(
        execution=exe, is_completed=True,
    ).count()
    if total_stages > 0 and done_stages >= total_stages:
        exe.status = 'completed'
        exe.completed_at = timezone.now()
        exe.save(update_fields=['status', 'completed_at'])

    exe.refresh_from_db()
    return Response(_serialize_execution(exe, with_stages=True))
