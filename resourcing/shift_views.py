"""Shift templates and the weekly shift schedule (Phase 11).

* /resourcing/shifts/                     — week grid; managers see everyone,
                                            other technicians see their own row
* /resourcing/shifts/templates/           — templates (managers)
* /resourcing/shifts/assign/              — add a weekly assignment (POST)
* /resourcing/shifts/assignments/<pk>/delete/

Who manages shifts: MSP technicians holding `resourcing_approve_leave` (the
people who already approve PTO) or `routing_manage_rules` (who already
manage on-call), and superusers. Customer users never reach these pages.
"""
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog

from . import shifts
from .models import ShiftAssignment, ShiftTemplate, WorkingHours

WEEKDAYS = [(i, name[:3]) for i, name in WorkingHours.WEEKDAYS]


def _is_tech(user):
    from psa.visibility import is_msp_staff
    return bool(user.is_authenticated and user.is_active and is_msp_staff(user))


def can_manage_shifts(user):
    if not _is_tech(user):
        return False
    if user.is_superuser:
        return True
    from accounts.permission_utils import user_has_perm
    return user_has_perm(user, 'resourcing_approve_leave') or user_has_perm(user, 'routing_manage_rules')


def can_view_team(user):
    if not _is_tech(user):
        return False
    if user.is_superuser or can_manage_shifts(user):
        return True
    from accounts.permission_utils import user_has_perm
    return user_has_perm(user, 'resourcing_view_team')


def _audit(request, action, obj, description):
    try:
        from core.client_ip import get_client_ip
        ip = get_client_ip(request)
    except Exception:  # noqa: BLE001
        ip = None
    AuditLog.log(user=request.user, action=action, object_type=f'resourcing.{type(obj).__name__}',
                 object_id=obj.pk, object_repr=str(obj)[:200], description=description[:1000],
                 ip_address=ip, path=request.path)


def _parse_date(raw, default=None):
    try:
        return datetime.strptime((raw or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return default


def _parse_time(raw):
    try:
        return datetime.strptime((raw or '').strip(), '%H:%M').time()
    except ValueError:
        return None


@login_required
def schedule(request):
    if not _is_tech(request.user):
        raise Http404()
    from psa.visibility import msp_technicians
    start = shifts.week_start(_parse_date(request.GET.get('week'), timezone.localdate()))
    team = None
    if can_view_team(request.user):
        users = msp_technicians()
        team_id = request.GET.get('team') or ''
        if team_id.isdigit():
            team = Group.objects.filter(pk=int(team_id)).first()
            if team is not None:
                users = users.filter(groups=team)
    else:
        users = [request.user]
    rows = shifts.week_grid(users, start)
    manage = can_manage_shifts(request.user)
    return render(request, 'resourcing/shift_schedule.html', {
        'rows': rows, 'start': start, 'days': [start + timedelta(days=i) for i in range(7)],
        'prev_week': start - timedelta(days=7), 'next_week': start + timedelta(days=7),
        'can_manage': manage, 'can_view_team': can_view_team(request.user),
        'templates': ShiftTemplate.objects.filter(is_active=True) if manage else [],
        'technicians': msp_technicians() if manage else [],
        'teams': Group.objects.order_by('name'), 'team': team, 'weekdays': WEEKDAYS,
        'assignments': (ShiftAssignment.objects.select_related('template', 'user', 'team')
                        .order_by('template__start_time', 'pk') if manage else []),
        'conflict_count': sum(r['conflicts'] for r in rows),
        'today': timezone.localdate(),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def templates(request):
    if not can_manage_shifts(request.user):
        raise Http404()
    if request.method == 'POST':
        if request.POST.get('delete'):
            tpl = get_object_or_404(ShiftTemplate, pk=request.POST['delete'])
            used = tpl.assignments.count()
            if used:
                tpl.is_active = False
                tpl.save(update_fields=['is_active', 'updated_at'])
                messages.info(request, f'"{tpl.name}" is used by {used} assignment(s), so it was switched off '
                                       'instead of deleted. Switched-off shifts are ignored everywhere.')
                _audit(request, 'update', tpl, f'Shift template "{tpl.name}" switched off')
            else:
                _audit(request, 'delete', tpl, f'Shift template "{tpl.name}" deleted')
                tpl.delete()
                messages.success(request, 'Shift template deleted.')
            return redirect('resourcing:shift_templates')
        pk = request.POST.get('pk') or ''
        tpl = get_object_or_404(ShiftTemplate, pk=pk) if pk.isdigit() else ShiftTemplate()
        start, end = _parse_time(request.POST.get('start_time')), _parse_time(request.POST.get('end_time'))
        name = (request.POST.get('name') or '').strip()[:100]
        if not name or start is None or end is None:
            messages.error(request, 'A shift needs a name, a start and an end.')
            return redirect('resourcing:shift_templates')
        if start == end:
            messages.error(request, 'Start and end are the same; for a 24-hour shift use 00:00–23:59.')
            return redirect('resourcing:shift_templates')
        tpl.name, tpl.start_time, tpl.end_time = name, start, end
        tpl.is_on_call = request.POST.get('is_on_call') == 'on'
        tpl.is_active = request.POST.get('is_active', 'on') == 'on'
        tpl.color = ''.join(ch for ch in (request.POST.get('color') or '') if ch.isalnum() or ch == '#')[:20]
        tpl.notes = (request.POST.get('notes') or '').strip()[:200]
        created = tpl.pk is None
        tpl.save()
        _audit(request, 'create' if created else 'update', tpl, f'Shift template saved: {tpl}')
        messages.success(request, f'Saved "{tpl.name}".')
        return redirect('resourcing:shift_templates')
    edit = None
    if (request.GET.get('edit') or '').isdigit():
        edit = ShiftTemplate.objects.filter(pk=int(request.GET['edit'])).first()
    return render(request, 'resourcing/shift_templates.html', {
        'templates': ShiftTemplate.objects.all(), 'edit': edit,
    })


@login_required
@require_http_methods(['POST'])
def assign(request):
    if not can_manage_shifts(request.user):
        raise Http404()
    from psa.visibility import msp_technicians
    back = request.POST.get('next') or ''
    back = back if back.startswith('/') and not back.startswith('//') else None
    tpl = ShiftTemplate.objects.filter(pk=request.POST.get('template') or 0, is_active=True).first()
    user = team = None
    if (request.POST.get('user') or '').isdigit():
        user = msp_technicians().filter(pk=int(request.POST['user'])).first()
    elif (request.POST.get('team') or '').isdigit():
        team = Group.objects.filter(pk=int(request.POST['team'])).first()
    days = sorted({int(d) for d in request.POST.getlist('weekdays') if d.isdigit() and int(d) < 7})
    start = _parse_date(request.POST.get('effective_from'), timezone.localdate())
    until = _parse_date(request.POST.get('effective_until'))
    problem = ''
    if tpl is None:
        problem = 'Choose an active shift template.'
    elif user is None and team is None:
        problem = 'Choose a technician or a team.'
    elif not days:
        problem = 'Pick at least one weekday.'
    elif until and until < start:
        problem = 'The end date must be on or after the start date.'
    if problem:
        messages.error(request, problem)
        return redirect(back or 'resourcing:shift_schedule')
    a = ShiftAssignment.objects.create(template=tpl, user=user, team=team, weekdays=days,
                                       effective_from=start, effective_until=until,
                                       notes=(request.POST.get('notes') or '').strip()[:200],
                                       created_by=request.user)
    _audit(request, 'create', a, f'Shift assignment: {a}')
    # Show PTO clashes straight away, for the next four weeks.
    clashes = []
    targets = [user] if user else list(team.user_set.filter(is_active=True))
    for u in targets[:50]:
        clashes += [f'{u.get_username()} {c}' for c in shifts.pto_conflicts(u, start, start + timedelta(days=27))]
    if clashes:
        messages.warning(request, 'Saved, but it clashes with leave: ' + '; '.join(clashes[:5])
                         + (f' (and {len(clashes) - 5} more)' if len(clashes) > 5 else ''))
    else:
        messages.success(request, 'Shift assignment saved.')
    return redirect(back or 'resourcing:shift_schedule')


@login_required
@require_http_methods(['POST'])
def assignment_delete(request, pk):
    if not can_manage_shifts(request.user):
        raise Http404()
    a = get_object_or_404(ShiftAssignment, pk=pk)
    _audit(request, 'delete', a, f'Shift assignment removed: {a}')
    a.delete()
    messages.success(request, 'Shift assignment removed.')
    back = request.POST.get('next') or ''
    return redirect(back if back.startswith('/') and not back.startswith('//') else 'resourcing:shift_schedule')
