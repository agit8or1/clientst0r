"""The weekly shift schedule, read by dispatch, on-call and routing.

A technician's shifts come from ShiftAssignment rows naming them directly or
naming a team (auth.Group) they belong to. Shift times are wall-clock times
in the technician's profile time zone; a shift whose end is at or before its
start finishes the next day.

Availability, in one place (`availability_problem`):
  * approved leave on the day                         -> unavailable
  * the technician has a shift schedule               -> available only
                                                         during a shift
  * otherwise, WorkingHours rows                      -> as before
  * neither                                           -> available

Technicians without any shift assignment behave exactly as before this
feature, so upgrades change nothing until a schedule is entered.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from django.db.models import Q
from django.utils import timezone


@dataclass
class Shift:
    template: object
    assignment: object
    starts_at: datetime
    ends_at: datetime

    @property
    def on_call(self):
        return bool(self.template.is_on_call)

    @property
    def team_id(self):
        return self.assignment.team_id

    @property
    def label(self):
        return f'{self.template.name} {self.template.start_time:%H:%M}–{self.template.end_time:%H:%M}'


def user_tz(user, fallback=''):
    from zoneinfo import ZoneInfo
    name = getattr(getattr(user, 'profile', None), 'timezone', '') or fallback
    try:
        return ZoneInfo(name) if name else timezone.get_default_timezone()
    except Exception:  # noqa: BLE001
        return timezone.get_default_timezone()


def _team_ids(user):
    return list(user.groups.values_list('pk', flat=True))


def assignments_qs(user):
    from .models import ShiftAssignment
    return (ShiftAssignment.objects
            .filter(Q(user=user) | Q(team_id__in=_team_ids(user)))
            .filter(template__is_active=True)
            .select_related('template', 'team'))


def has_schedule(user, on=None) -> bool:
    """Has any shift assignment that has not ended by `on` (default today)."""
    on = on or timezone.localdate()
    return assignments_qs(user).filter(Q(effective_until__isnull=True) | Q(effective_until__gte=on)).exists()


def shifts_on(user, day: date, *, rows=None, tz=None) -> List[Shift]:
    """Shifts that start on `day` (the technician's local date)."""
    tz = tz or user_tz(user)
    rows = rows if rows is not None else list(assignments_qs(user))
    out = []
    for a in rows:
        if not a.covers(day):
            continue
        t = a.template
        start = datetime.combine(day, t.start_time, tzinfo=tz)
        end_day = day + timedelta(days=1) if t.overnight else day
        end = datetime.combine(end_day, t.end_time, tzinfo=tz)
        out.append(Shift(template=t, assignment=a, starts_at=start, ends_at=end))
    out.sort(key=lambda s: (s.starts_at, s.template.name))
    return out


def shift_at(user, when=None, *, rows=None) -> Optional[Shift]:
    """The shift running at `when`, including one that began the day before."""
    when = when or timezone.now()
    tz = user_tz(user)
    local_day = when.astimezone(tz).date()
    rows = rows if rows is not None else list(assignments_qs(user))
    for day in (local_day, local_day - timedelta(days=1)):
        for s in shifts_on(user, day, rows=rows, tz=tz):
            if s.starts_at <= when < s.ends_at:
                return s
    return None


def on_call_shift(user, when=None, team_id=None) -> Optional[Shift]:
    """A running on-call shift. A team-assigned shift counts for that team
    only (when the caller names one); a shift assigned to the technician
    directly counts for every team, like OnCallShift with no team."""
    when = when or timezone.now()
    rows = [a for a in assignments_qs(user) if a.template.is_on_call]
    if not rows:
        return None
    s = shift_at(user, when, rows=rows)
    if s is None:
        return None
    if team_id and s.team_id and int(s.team_id) != int(team_id):
        return None
    return s


def _working_hours_problem(user, local):
    from .models import WorkingHours
    rows = list(WorkingHours.objects.filter(user=user, is_active=True))
    if rows:
        t = local.time()
        if not any(r.weekday == local.weekday() and r.start_time <= t < r.end_time for r in rows):
            return 'outside their working hours'
    return None


def availability_problem(user, when=None, *, tz_fallback='') -> Optional[str]:
    """None when the technician is available at `when`, else why not."""
    from .models import LeaveRequest
    when = when or timezone.now()
    local = when.astimezone(user_tz(user, tz_fallback))
    if LeaveRequest.is_user_on_leave(user, local.date()):
        return 'on approved leave today'
    if has_schedule(user, on=local.date()):
        if shift_at(user, when) is None:
            return 'outside their scheduled shifts'
        return None
    return _working_hours_problem(user, local)


def is_working(user, when=None) -> bool:
    """Shift-aware "on shift now", ignoring leave. Falls back to the
    WorkingHours rule (no rows = always working)."""
    when = when or timezone.now()
    if has_schedule(user, on=when.astimezone(user_tz(user)).date()):
        return shift_at(user, when) is not None
    return _working_hours_problem(user, when.astimezone(user_tz(user))) is None


# ---------------------------------------------------------------------------
# Weekly grid (schedule page + dispatch)
# ---------------------------------------------------------------------------

def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_grid(users, start: date, days: int = 7):
    """Rows of {'user', 'cells': [{'day', 'shifts', 'leave', 'pending_leave',
    'holiday', 'conflict'}]} for the schedule page.

    `conflict` is the plain-language PTO clash: a shift scheduled on a day the
    technician has approved leave (or a pending request, flagged softer)."""
    from .models import Holiday, LeaveRequest
    end = start + timedelta(days=days - 1)
    users = list(users)
    leave = {}
    for lr in (LeaveRequest.objects.filter(user__in=users, status__in=('approved', 'pending'),
                                           start_date__lte=end, end_date__gte=start)):
        leave.setdefault(lr.user_id, []).append(lr)
    holidays = {}
    for h in Holiday.objects.filter(organization__isnull=True):
        holidays.setdefault((h.date.month, h.date.day) if h.is_recurring_yearly else h.date, h)
    rows = []
    for u in users:
        rows_for_user = list(assignments_qs(u))
        tz = user_tz(u)
        cells = []
        for i in range(days):
            day = start + timedelta(days=i)
            shifts = shifts_on(u, day, rows=rows_for_user, tz=tz)
            approved = [lr for lr in leave.get(u.pk, []) if lr.status == 'approved'
                        and lr.start_date <= day <= lr.end_date]
            pending = [lr for lr in leave.get(u.pk, []) if lr.status == 'pending'
                       and lr.start_date <= day <= lr.end_date]
            holiday = holidays.get(day) or holidays.get((day.month, day.day))
            conflict = ''
            if shifts and approved:
                conflict = f'Scheduled while on approved {approved[0].get_leave_type_display().lower()}'
            elif shifts and pending:
                conflict = f'Pending {pending[0].get_leave_type_display().lower()} request on a scheduled day'
            elif shifts and holiday:
                conflict = f'Scheduled on {holiday.name}'
            cells.append({'day': day, 'shifts': shifts, 'leave': approved, 'pending_leave': pending,
                          'holiday': holiday, 'conflict': conflict})
        rows.append({'user': u, 'cells': cells,
                     'conflicts': sum(1 for c in cells if c['conflict'])})
    return rows


def pto_conflicts(user, start: date, end: date) -> List[str]:
    """Plain-language list of scheduled days that clash with leave."""
    rows = week_grid([user], start, (end - start).days + 1)
    return [f'{c["day"].isoformat()}: {c["conflict"]}' for c in rows[0]['cells'] if c['conflict']]
