"""
Mobile API dispatch + scheduling endpoints (v3.17.457).

Surfaces what a tech has on their plate: scheduled tasks they're
assigned to, plus their open tickets. Lets them sign off on assignments
and comment on tasks.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status as drf_status
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .scoping import accessible_org_ids
from psa.visibility import customer_visible_tickets


def _serialize_assignment(a) -> dict:
    t = a.task
    return {
        # v3.17.478 — `kind` discriminator so the mobile calendar /
        # agenda can render tasks and tickets in one list.
        'kind': 'task',
        'assignment_id': a.id,
        'task_id': t.id,
        'task_title': t.title,
        'task_description': t.description,
        'task_priority': t.priority,
        'task_status': t.status,
        'task_due_date': t.due_date.isoformat() if t.due_date else None,
        'organization_id': t.organization_id,
        'organization_name': t.organization.name if t.organization_id else None,
        'acknowledged': a.acknowledged,
        'acknowledged_at': a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        'notes': a.notes or '',
        'recurrence': t.recurrence,
    }


def _serialize_ticket_calendar(t) -> dict:
    """
    v3.17.478 — compact ticket payload for the calendar / agenda. We keep
    the same shape as `_serialize_assignment` so a single ListRow can
    render either without branching: same field names where possible,
    `kind='ticket'` discriminator, and the ticket's `resolution_due_at`
    aliased as `task_due_date` so existing calendar UI code keeps working.
    """
    org_name = None
    if t.organization_id and getattr(t, 'organization', None) is not None:
        org_name = getattr(t.organization, 'name', None)
    return {
        'kind': 'ticket',
        'ticket_id': t.id,
        'ticket_number': t.ticket_number,
        'task_title': t.subject,
        'task_priority': t.priority.code if t.priority_id else None,
        'task_status': t.status.name if t.status_id else None,
        'task_due_date': t.resolution_due_at.isoformat()
            if t.resolution_due_at else None,
        'organization_id': t.organization_id,
        'organization_name': org_name,
    }


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def dispatch_board_view(request):
    """
    GET /api/mobile/v1/dispatch/

    Combines scheduled-task assignments + open tickets assigned to the
    caller. Buckets by:
      - overdue:    due_date in the past, not completed
      - today:      due_date inside today's window OR no due_date
      - upcoming:   due_date in the future
      - tickets:    open ticket count + top 5 by -updated_at
    """
    from scheduling.models import TaskAssignment

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timezone.timedelta(days=1)

    qs = (TaskAssignment.objects
          .filter(user=request.user, task__status__in=['pending', 'in_progress', 'overdue'])
          .select_related('task', 'task__organization'))
    overdue, today, upcoming = [], [], []
    for a in qs:
        d = a.task.due_date
        if d and d < now and a.task.status != 'completed':
            overdue.append(a)
        elif d is None or (today_start <= d < today_end):
            today.append(a)
        else:
            upcoming.append(a)

    # Tickets the user has open work on
    tickets_data = {'open_count': 0, 'recent': []}
    try:
        from psa.models import Ticket
        from .views_tickets import _serialize_ticket
        org_ids = accessible_org_ids(request.user)
        ticket_qs = (customer_visible_tickets(Ticket.objects.all(), request.user)
                     .filter(organization_id__in=org_ids,
                             assigned_to=request.user,
                             status__is_terminal=False)
                     .select_related('status', 'priority'))
        tickets_data['open_count'] = ticket_qs.count()
        tickets_data['recent'] = [
            _serialize_ticket(t) for t in
            ticket_qs.order_by('-updated_at')[:5]
        ]
    except Exception:
        pass

    return Response({
        'overdue':  [_serialize_assignment(a) for a in overdue],
        'today':    [_serialize_assignment(a) for a in today],
        'upcoming': [_serialize_assignment(a) for a in upcoming],
        'tickets':  tickets_data,
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def dispatch_calendar_view(request):
    """
    GET /api/mobile/v1/dispatch/calendar/?month=YYYY-MM

    Calendar grouping for the caller's `TaskAssignment` rows whose task
    has a `due_date` inside the requested month. Returns a flat map
    `{YYYY-MM-DD: [assignment dicts], ...}` so the mobile calendar can
    render dots / counts per day. Days with no assignments are omitted
    rather than returned as empty lists.

    `month` defaults to the current local month. Format YYYY-MM.
    """
    from datetime import date, timedelta
    from django.utils import timezone
    from scheduling.models import TaskAssignment

    month_raw = (request.query_params.get('month') or '').strip()
    today = timezone.localdate()
    if month_raw:
        try:
            year, mon = month_raw.split('-')
            start = date(int(year), int(mon), 1)
        except (ValueError, IndexError):
            return Response({'detail': 'month must be YYYY-MM'}, status=400)
    else:
        start = today.replace(day=1)

    # End: first day of next month.
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    qs = (TaskAssignment.objects
          .filter(user=request.user,
                  task__due_date__gte=start,
                  task__due_date__lt=end)
          .select_related('task', 'task__organization'))

    bucketed: dict[str, list[dict]] = {}
    for a in qs:
        d = a.task.due_date.date().isoformat() if a.task.due_date else None
        if not d:
            continue
        bucketed.setdefault(d, []).append(_serialize_assignment(a))

    # v3.17.478 — also fold tickets assigned to the caller whose
    # `resolution_due_at` lands inside the month. Same per-day bucket
    # shape; rows carry a `kind='ticket'` discriminator. Skipped silently
    # if PSA isn't installed (matches the dashboard pattern).
    try:
        from psa.models import Ticket
        from django.db.models import Q
        from datetime import datetime, time as dtime
        # Restrict to tickets the caller can see: assigned to them
        # OR they have tickets_view_all. Membership-scoped reads aren't
        # filtered here because the calendar payload is per-user noise,
        # not cross-org leakage.
        ticket_qs = (customer_visible_tickets(Ticket.objects.all(), request.user)
                     .filter(resolution_due_at__gte=datetime.combine(start, dtime.min),
                             resolution_due_at__lt=datetime.combine(end, dtime.min))
                     .filter(Q(assigned_to=request.user)
                             | Q(organization_id__in=accessible_org_ids(request.user)))
                     .filter(status__is_terminal=False)
                     .select_related('status', 'priority', 'organization')
                     .distinct())
        for t in ticket_qs:
            d = t.resolution_due_at.date().isoformat()
            bucketed.setdefault(d, []).append(_serialize_ticket_calendar(t))
    except Exception:
        pass

    return Response({
        'month': start.strftime('%Y-%m'),
        'today': today.isoformat(),
        'days': bucketed,
    })


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def create_scheduled_task_view(request):
    """
    POST /api/mobile/v1/dispatch/tasks/   (v3.17.479)

    Body: `{organization_id, title, due_at, description?, priority?,
            assignee_id?}`. `due_at` is ISO 8601. `priority` ∈ {low,
    normal, high, urgent} (default 'normal'). `assignee_id` defaults
    to the caller — pass `null` to leave the task unassigned.

    Used by the mobile calendar's "Schedule on this day" action so a
    tech can drop a new ScheduledTask onto a calendar day without
    leaving the app.
    """
    from datetime import datetime
    from django.utils import timezone as _tz
    from django.contrib.auth.models import User
    from scheduling.models import ScheduledTask, TaskAssignment

    data = request.data or {}
    org_id = data.get('organization_id')
    try:
        org_id = int(org_id) if org_id is not None else None
    except (TypeError, ValueError):
        return Response({'detail': 'organization_id must be an integer'},
                        status=drf_status.HTTP_400_BAD_REQUEST)
    if not org_id or org_id not in list(accessible_org_ids(request.user)):
        return Response(
            {'detail': 'organization_id required and must be accessible'},
            status=drf_status.HTTP_403_FORBIDDEN,
        )

    title = (data.get('title') or '').strip()
    if not title:
        return Response({'detail': 'title is required'},
                        status=drf_status.HTTP_400_BAD_REQUEST)

    due_raw = data.get('due_at') or data.get('due_date')
    due_at = None
    if due_raw:
        try:
            due_at = datetime.fromisoformat(str(due_raw).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return Response({'detail': 'due_at must be ISO 8601'},
                            status=drf_status.HTTP_400_BAD_REQUEST)
        if _tz.is_naive(due_at):
            due_at = _tz.make_aware(due_at)

    priority = (data.get('priority') or 'normal').strip().lower()
    if priority not in {'low', 'normal', 'high', 'urgent'}:
        priority = 'normal'

    task = ScheduledTask.objects.create(
        organization_id=org_id,
        title=title[:255],
        description=(data.get('description') or '')[:5000],
        priority=priority,
        due_date=due_at,
        created_by=request.user,
        status='pending',
    )

    # Default assignee is the caller. Pass `assignee_id=null` to skip;
    # pass an explicit id to assign someone else.
    if 'assignee_id' in data:
        raw = data.get('assignee_id')
        if raw not in (None, '', 0):
            try:
                assignee = User.objects.get(pk=int(raw))
                TaskAssignment.objects.create(task=task, user=assignee)
            except (User.DoesNotExist, ValueError, TypeError):
                # The task was already created; just skip the assignment
                # rather than 500ing.
                pass
    else:
        TaskAssignment.objects.create(task=task, user=request.user)

    # Re-fetch with org so the serializer can render organization_name.
    task = (ScheduledTask.objects
            .select_related('organization').get(pk=task.pk))
    # Return as a calendar-shaped row + the created assignment id (if any)
    # so the mobile client can drop it into the calendar bucket directly.
    assignment = TaskAssignment.objects.filter(
        task=task, user=request.user,
    ).first()
    if assignment is None:
        assignment = TaskAssignment.objects.filter(task=task).first()
    if assignment is not None:
        return Response(_serialize_assignment(assignment),
                        status=drf_status.HTTP_201_CREATED)
    # Edge case: task created but no assignment (caller passed null + no fallback)
    return Response({
        'kind': 'task',
        'task_id': task.id,
        'task_title': task.title,
        'task_due_date': task.due_date.isoformat() if task.due_date else None,
        'task_priority': task.priority,
        'task_status': task.status,
        'organization_id': task.organization_id,
        'organization_name': task.organization.name if task.organization_id else None,
    }, status=drf_status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def dispatch_upcoming_view(request):
    """
    GET /api/mobile/v1/dispatch/upcoming/?days=7

    v3.17.478 — compact agenda for the mobile dashboard widget. Returns
    one row per day from today through today + N-1, each carrying a
    flattened mix of `TaskAssignment` rows (caller's assignments) and
    `Ticket` rows (caller's accessible tickets with a
    `resolution_due_at`) due that day. `days` is clamped to [1, 14].
    """
    from datetime import date, timedelta, datetime, time as dtime
    from scheduling.models import TaskAssignment

    try:
        n = int(request.query_params.get('days', 7))
    except (TypeError, ValueError):
        n = 7
    n = max(1, min(n, 14))

    today = timezone.localdate()
    end = today + timedelta(days=n)

    # Empty buckets for every day in range so the mobile UI can render a
    # uniform N-row strip without filling in gaps.
    buckets: list[dict] = [
        {'date': (today + timedelta(days=i)).isoformat(), 'items': []}
        for i in range(n)
    ]
    by_date = {b['date']: b for b in buckets}

    # Tasks
    task_qs = (TaskAssignment.objects
               .filter(user=request.user,
                       task__due_date__gte=datetime.combine(today, dtime.min),
                       task__due_date__lt=datetime.combine(end, dtime.min))
               .select_related('task', 'task__organization'))
    for a in task_qs:
        d = a.task.due_date.date().isoformat() if a.task.due_date else None
        if d and d in by_date:
            by_date[d]['items'].append(_serialize_assignment(a))

    # Tickets
    try:
        from psa.models import Ticket
        from django.db.models import Q
        ticket_qs = (customer_visible_tickets(Ticket.objects.all(), request.user)
                     .filter(resolution_due_at__gte=datetime.combine(today, dtime.min),
                             resolution_due_at__lt=datetime.combine(end, dtime.min))
                     .filter(Q(assigned_to=request.user)
                             | Q(organization_id__in=accessible_org_ids(request.user)))
                     .filter(status__is_terminal=False)
                     .select_related('status', 'priority', 'organization')
                     .distinct())
        for t in ticket_qs:
            d = t.resolution_due_at.date().isoformat()
            if d in by_date:
                by_date[d]['items'].append(_serialize_ticket_calendar(t))
    except Exception:
        pass

    return Response({
        'today': today.isoformat(),
        'days': buckets,
    })


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def task_acknowledge_view(request, pk: int):
    """
    POST /api/mobile/v1/dispatch/assignments/<assignment_id>/ack/

    Body: `{notes?}`. Marks this assignment acknowledged. Triggers the
    task's completion check (via `TaskAssignment.sign_off`), which can
    auto-complete the task if `require_all_signoffs` is satisfied.
    """
    from scheduling.models import TaskAssignment

    try:
        a = TaskAssignment.objects.select_related('task').get(
            pk=pk, user=request.user,
        )
    except TaskAssignment.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    notes = (request.data.get('notes') or '').strip()[:2000] if request.data else ''
    a.sign_off(notes=notes)
    a.refresh_from_db()
    return Response(_serialize_assignment(a))


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def task_comment_view(request, pk: int):
    """
    POST /api/mobile/v1/dispatch/tasks/<task_id>/comments/

    Body: `{body}`. Adds a `TaskComment` from the caller.
    """
    from scheduling.models import ScheduledTask, TaskAssignment, TaskComment

    # Caller must have an assignment on this task
    has_assignment = TaskAssignment.objects.filter(
        task_id=pk, user=request.user,
    ).exists()
    if not has_assignment:
        return Response({'detail': 'Not found'}, status=404)

    body = (request.data.get('body') or '').strip() if request.data else ''
    if not body:
        return Response({'detail': 'body is required'}, status=400)

    comment = TaskComment.objects.create(
        task_id=pk, author=request.user, body=body[:5000],
    )
    return Response({
        'id': comment.id,
        'task_id': comment.task_id,
        'author_id': comment.author_id,
        'body': comment.body,
        'created_at': comment.created_at.isoformat() if hasattr(comment, 'created_at') and comment.created_at else None,
    }, status=drf_status.HTTP_201_CREATED)
