"""
Scheduling views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta
from collections import defaultdict
from core.middleware import get_request_organization
from core.decorators import require_admin, require_write
from .models import (
    ScheduledTask, SchedulerWallboard, TaskAssignment, TaskComment,
)
from .forms import ScheduledTaskForm, TaskSignOffForm, TaskCommentForm, TaskAssignUsersForm


@login_required
def scheduling_dashboard(request):
    """Dashboard with summary stats and upcoming tasks."""
    org = get_request_organization(request)
    now = timezone.now()
    week_from_now = now + timedelta(days=7)

    base_qs = ScheduledTask.objects.for_organization(org) if org else ScheduledTask.objects.none()

    total_pending = base_qs.filter(status__in=('pending', 'in_progress')).count()
    overdue_count = sum(1 for t in base_qs.filter(status__in=('pending', 'in_progress')) if t.is_overdue)

    upcoming = base_qs.filter(
        status__in=('pending', 'in_progress'),
        due_date__gte=now,
        due_date__lte=week_from_now,
    ).order_by('due_date')[:10]

    # My tasks needing sign-off
    my_assignments = TaskAssignment.objects.filter(
        user=request.user,
        acknowledged=False,
        task__status__in=('pending', 'in_progress'),
        task__organization=org,
    ).select_related('task').order_by('task__due_date') if org else []

    my_pending_count = len(list(my_assignments))

    return render(request, 'scheduling/dashboard.html', {
        'total_pending': total_pending,
        'overdue_count': overdue_count,
        'upcoming_count': upcoming.count() if hasattr(upcoming, 'count') else len(list(upcoming)),
        'my_pending_count': my_pending_count,
        'upcoming_tasks': upcoming,
        'my_assignments': my_assignments,
    })


@login_required
def task_list(request):
    """List scheduled tasks with filters."""
    org = get_request_organization(request)
    tasks = ScheduledTask.objects.for_organization(org).prefetch_related(
        'task_assignments__user'
    ) if org else ScheduledTask.objects.none()

    filter_status = request.GET.get('status', '')
    if filter_status:
        tasks = tasks.filter(status=filter_status)

    filter_priority = request.GET.get('priority', '')
    if filter_priority:
        tasks = tasks.filter(priority=filter_priority)

    if request.GET.get('assigned_to_me'):
        tasks = tasks.filter(task_assignments__user=request.user)

    if request.GET.get('overdue'):
        now = timezone.now()
        tasks = tasks.filter(
            due_date__lt=now,
            status__in=('pending', 'in_progress')
        )

    return render(request, 'scheduling/task_list.html', {
        'tasks': tasks,
        'status_choices': ScheduledTask.STATUS_CHOICES,
        'priority_choices': ScheduledTask.PRIORITY_CHOICES,
        'filter_status': filter_status,
        'filter_priority': filter_priority,
        'is_overdue_filter': bool(request.GET.get('overdue')),
    })


@login_required
def task_create(request):
    """Create a new scheduled task and assign users."""
    org = get_request_organization(request)

    if request.method == 'POST':
        form = ScheduledTaskForm(request.POST, org=org)
        assign_form = TaskAssignUsersForm(request.POST, org=org)
        if form.is_valid() and assign_form.is_valid():
            task = form.save(commit=False)
            task.organization = org
            task.created_by = request.user
            task.save()
            form.save_m2m()

            for user in assign_form.cleaned_data.get('users', []):
                TaskAssignment.objects.get_or_create(task=task, user=user)

            messages.success(request, f'Task "{task.title}" created successfully.')
            return redirect('scheduling:task_detail', pk=task.pk)
    else:
        form = ScheduledTaskForm(org=org)
        assign_form = TaskAssignUsersForm(org=org)

    return render(request, 'scheduling/task_form.html', {
        'form': form,
        'assign_form': assign_form,
        'title': 'New Scheduled Task',
    })


@login_required
def task_detail(request, pk):
    """Show task details, assignments, comments."""
    org = get_request_organization(request)
    task = get_object_or_404(ScheduledTask, pk=pk, organization=org)
    assignments = task.task_assignments.select_related('user').all()
    comments = task.comments.select_related('author').order_by('created_at')

    # Check if the current user can sign off
    user_assignment = None
    try:
        user_assignment = assignments.get(user=request.user)
    except TaskAssignment.DoesNotExist:
        pass

    sign_off_form = None
    if user_assignment and not user_assignment.acknowledged:
        if request.method == 'POST' and 'sign_off_submit' in request.POST:
            sign_off_form = TaskSignOffForm(request.POST)
            if sign_off_form.is_valid():
                user_assignment.sign_off(notes=sign_off_form.cleaned_data.get('notes', ''))
                messages.success(request, 'Signed off successfully.')
                return redirect('scheduling:task_detail', pk=task.pk)
        else:
            sign_off_form = TaskSignOffForm()

    # Comment form
    comment_form = None
    if request.method == 'POST' and 'comment_submit' in request.POST:
        comment_form = TaskCommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.task = task
            comment.author = request.user
            comment.save()
            messages.success(request, 'Comment added.')
            return redirect('scheduling:task_detail', pk=task.pk)
    else:
        comment_form = TaskCommentForm()

    return render(request, 'scheduling/task_detail.html', {
        'task': task,
        'assignments': assignments,
        'comments': comments,
        'user_assignment': user_assignment,
        'sign_off_form': sign_off_form,
        'comment_form': comment_form,
    })


@login_required
@require_admin
def task_edit(request, pk):
    """Edit an existing scheduled task."""
    org = get_request_organization(request)
    task = get_object_or_404(ScheduledTask, pk=pk, organization=org)

    if request.method == 'POST':
        form = ScheduledTaskForm(request.POST, instance=task, org=org)
        assign_form = TaskAssignUsersForm(request.POST, org=org)
        if form.is_valid() and assign_form.is_valid():
            form.save()
            selected_users = assign_form.cleaned_data.get('users', [])
            # Update assignments: remove users not selected, add new ones
            current_user_ids = set(task.task_assignments.values_list('user_id', flat=True))
            selected_user_ids = set(u.id for u in selected_users)
            # Remove deselected
            task.task_assignments.filter(user_id__in=(current_user_ids - selected_user_ids)).delete()
            # Add new
            for user_id in (selected_user_ids - current_user_ids):
                from django.contrib.auth.models import User
                TaskAssignment.objects.get_or_create(task=task, user_id=user_id)

            messages.success(request, f'Task "{task.title}" updated.')
            return redirect('scheduling:task_detail', pk=task.pk)
    else:
        form = ScheduledTaskForm(instance=task, org=org)
        current_users = task.assigned_to.all()
        assign_form = TaskAssignUsersForm(org=org, initial={'users': current_users})

    return render(request, 'scheduling/task_form.html', {
        'form': form,
        'assign_form': assign_form,
        'task': task,
        'title': f'Edit: {task.title}',
    })


@login_required
@require_admin
def task_delete(request, pk):
    """Delete a scheduled task."""
    org = get_request_organization(request)
    task = get_object_or_404(ScheduledTask, pk=pk, organization=org)

    if request.method == 'POST':
        title = task.title
        task.delete()
        messages.success(request, f'Task "{title}" deleted.')
        return redirect('scheduling:task_list')

    return render(request, 'scheduling/task_confirm_delete.html', {'task': task})


@login_required
def task_sign_off(request, pk):
    """Sign off on a task as the current user."""
    org = get_request_organization(request)
    task = get_object_or_404(ScheduledTask, pk=pk, organization=org)
    assignment = get_object_or_404(TaskAssignment, task=task, user=request.user)

    if request.method == 'POST':
        form = TaskSignOffForm(request.POST)
        if form.is_valid():
            assignment.sign_off(notes=form.cleaned_data.get('notes', ''))
            messages.success(request, 'Signed off successfully.')
    else:
        messages.error(request, 'Invalid request.')

    return redirect('scheduling:task_detail', pk=task.pk)


@login_required
@require_admin
def task_complete(request, pk):
    """Force-complete a task as an admin."""
    org = get_request_organization(request)
    task = get_object_or_404(ScheduledTask, pk=pk, organization=org)

    if request.method == 'POST':
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.completed_by = request.user
        task.save()
        messages.success(request, f'Task "{task.title}" marked as complete.')
        if task.recurrence != 'none':
            new_task = task.spawn_next_occurrence()
            if new_task:
                messages.info(request, f'Next occurrence created: due {new_task.due_date}.')

    return redirect('scheduling:task_detail', pk=task.pk)


@login_required
@require_admin
def task_cancel(request, pk):
    """Cancel a task."""
    org = get_request_organization(request)
    task = get_object_or_404(ScheduledTask, pk=pk, organization=org)

    if request.method == 'POST':
        task.status = 'cancelled'
        task.save()
        messages.success(request, f'Task "{task.title}" cancelled.')

    return redirect('scheduling:task_detail', pk=task.pk)


@login_required
@require_admin
def task_spawn_next(request, pk):
    """Manually spawn the next recurrence of a task."""
    org = get_request_organization(request)
    task = get_object_or_404(ScheduledTask, pk=pk, organization=org)

    if request.method == 'POST':
        new_task = task.spawn_next_occurrence()
        if new_task:
            messages.success(request, f'Next occurrence created.')
            return redirect('scheduling:task_detail', pk=new_task.pk)
        else:
            messages.error(request, 'Could not create next occurrence. Task may not be recurring or has no due date.')

    return redirect('scheduling:task_detail', pk=task.pk)


@login_required
def my_tasks(request):
    """Tasks assigned to the current user."""
    org = get_request_organization(request)
    assignments = TaskAssignment.objects.filter(
        user=request.user,
        task__status__in=('pending', 'in_progress'),
        task__organization=org,
    ).select_related('task', 'task__organization').order_by('task__due_date') if org else []

    return render(request, 'scheduling/my_tasks.html', {
        'assignments': assignments,
        'now': timezone.now(),
    })


@login_required
def overdue_tasks(request):
    """Tasks that are past their due date and not completed."""
    org = get_request_organization(request)
    now = timezone.now()
    tasks = ScheduledTask.objects.for_organization(org).filter(
        due_date__lt=now,
        status__in=('pending', 'in_progress'),
    ).order_by('due_date') if org else ScheduledTask.objects.none()

    return render(request, 'scheduling/task_list.html', {
        'tasks': tasks,
        'status_choices': ScheduledTask.STATUS_CHOICES,
        'priority_choices': ScheduledTask.PRIORITY_CHOICES,
        'filter_status': '',
        'filter_priority': '',
        'is_overdue_filter': True,
        'page_title': 'Overdue Tasks',
    })


@login_required
def task_calendar(request):
    """Calendar view - tasks grouped by due date."""
    org = get_request_organization(request)
    now = timezone.now()
    # Show next 60 days
    end_date = now + timedelta(days=60)

    tasks = ScheduledTask.objects.for_organization(org).filter(
        status__in=('pending', 'in_progress'),
        due_date__gte=now,
        due_date__lte=end_date,
    ).order_by('due_date') if org else ScheduledTask.objects.none()

    # Group by date
    grouped = defaultdict(list)
    for task in tasks:
        date_key = task.due_date.date()
        grouped[date_key].append(task)

    # Sort by date
    calendar_data = sorted(grouped.items())

    return render(request, 'scheduling/calendar.html', {
        'calendar_data': calendar_data,
        'now': now,
    })


# ---------------------------------------------------------------------------
# Phase 47 (v3.17.533) — public scheduler wallboard
# ---------------------------------------------------------------------------

def _wallboard_days(days_ahead):
    """Scheduled tasks grouped by day, oldest first.

    Shares the shape of the dashboard Schedule panel (v3.17.524) so the wall
    display and the dashboard cannot disagree about what is happening today.
    """
    from datetime import datetime, time, timedelta

    today = timezone.now().date()
    end = today + timedelta(days=max(1, min(int(days_ahead or 1), 14)))
    start_dt = timezone.make_aware(datetime.combine(today, time.min))
    end_dt = timezone.make_aware(datetime.combine(end, time.min))

    # Every client's work: this is a workshop board, and an MSP's day spans
    # clients. `show_client_names` controls whether the names are displayed.
    tasks = (ScheduledTask.objects
             .filter(due_date__gte=start_dt, due_date__lt=end_dt)
             .exclude(status__in=['completed', 'cancelled'])
             .select_related('organization', 'psa_ticket')
             .prefetch_related('assigned_to')
             .order_by('due_date'))

    buckets = {}
    for task in tasks:
        buckets.setdefault(task.due_date.date(), []).append(task)
    return [(day, buckets[day]) for day in sorted(buckets)]


def wallboard_public(request, token):
    """The board itself. No authentication — that is the point.

    A disabled or unknown token 404s identically. Distinguishing them would
    confirm to anyone probing that a board exists at that address.
    """
    from django.http import Http404
    from django.shortcuts import render

    board = SchedulerWallboard.objects.filter(
        token=token, is_enabled=True).first()
    if board is None:
        raise Http404('No wallboard here')

    response = render(request, 'scheduling/wallboard_public.html', {
        'board': board,
        'days': _wallboard_days(board.days_ahead),
        'generated_at': timezone.now(),
    })
    # An unauthenticated page listing customer work has no business in a shared
    # cache or a search index.
    response['Cache-Control'] = 'no-store, private'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@login_required
@require_admin
def wallboard_settings(request):
    """Enable, disable, configure and rotate the board's link."""
    from django.shortcuts import render

    board = SchedulerWallboard.get_board(user=request.user)

    if request.method == 'POST':
        action = request.POST.get('action') or 'save'

        if action == 'rotate':
            board.rotate_token()
            messages.warning(
                request,
                'Link rotated. Any screen still pointed at the old address will '
                'stop working until you re-open the new one on it.')
            return redirect('scheduling:wallboard_settings')

        board.is_enabled = request.POST.get('is_enabled') == 'on'
        board.title = (request.POST.get('title') or '').strip()[:120]
        board.show_client_names = request.POST.get('show_client_names') == 'on'
        board.show_technician_names = request.POST.get('show_technician_names') == 'on'
        board.show_ticket_numbers = request.POST.get('show_ticket_numbers') == 'on'
        try:
            board.days_ahead = max(1, min(int(request.POST.get('days_ahead') or 1), 14))
        except (TypeError, ValueError):
            board.days_ahead = 1
        try:
            board.refresh_seconds = int(request.POST.get('refresh_seconds') or 60)
        except (TypeError, ValueError):
            board.refresh_seconds = 60
        board.save()

        if board.is_enabled:
            messages.success(
                request,
                'Wallboard is live. Anyone with the link can read this '
                'schedule without signing in.')
        else:
            messages.success(request, 'Wallboard disabled. The link now 404s.')
        return redirect('scheduling:wallboard_settings')

    return render(request, 'scheduling/wallboard_settings.html', {
        'board': board,
        'public_url': request.build_absolute_uri(board.get_public_url()),
    })
