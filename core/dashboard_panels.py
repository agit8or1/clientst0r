"""
Dashboard Schedule + Tasks panels (v3.17.524).

Replaces three panels that showed what *had happened* (My Recent, Recent
Activity) or sat in isolation (Expiring Soon) with two that show what needs
doing next. Expiring items are folded into Tasks: an expiring password or
certificate is a thing somebody has to act on, which is what a task is.

The shapes here mirror the mobile agenda added in v3.17.478 — scheduled tasks
and ticket due dates on one timeline — so the two surfaces agree about what
"upcoming" means.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import F
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

SCHEDULE_DAYS = 7
OPEN_TASK_STATUSES = ('pending', 'in_progress', 'overdue')
TASK_LIMIT = 12
EXPIRY_WINDOW_DAYS = 30
# How far back an already-expired item stays on the list. Rows sort
# earliest-first, so without a floor a single record that lapsed years ago
# would pin the top of the panel forever.
EXPIRY_GRACE_DAYS = 30


@dataclass
class TaskRow:
    """One actionable row in the Tasks panel.

    Scheduled tasks and expiring things are different models, so the template
    gets a single flat shape rather than three parallel loops.
    """
    kind: str                 # 'task' | 'password' | 'expiration' | 'ssl'
    title: str
    url: str = ''
    due: Any = None           # date/datetime or None
    priority: str = 'normal'
    context: str = ''         # secondary line (org, host, ...)
    icon: str = 'fa-circle-check'

    @property
    def is_overdue(self) -> bool:
        if not self.due:
            return False
        now = timezone.now()
        if isinstance(self.due, datetime):
            due = due_aware(self.due)
            return due < now
        return self.due < now.date()

    @property
    def days_until(self):
        if not self.due:
            return None
        today = timezone.now().date()
        d = self.due.date() if isinstance(self.due, datetime) else self.due
        return (d - today).days


def due_aware(value: datetime) -> datetime:
    """Compare safely whether or not USE_TZ produced an aware value."""
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_default_timezone())
    return value


def panel_url(name: str, *args) -> str:
    """Resolve a route by name, never by a hand-written path.

    Hand-written paths in this module were wrong for three of the five links:
    tickets live at /psa/t/<pk>/ (not /psa/tickets/), expirations under
    monitoring (not core), and /monitoring/ has no route at all. A url of '' is
    rendered as a non-link rather than a dead one.
    """
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


@dataclass
class ScheduleDay:
    day: date
    items: list = field(default_factory=list)

    @property
    def is_today(self) -> bool:
        return self.day == timezone.now().date()


def get_schedule(user, organization, days: int = SCHEDULE_DAYS) -> list[ScheduleDay]:
    """Upcoming scheduled tasks and ticket deadlines, grouped by day.

    Only days that actually have something are returned — an agenda of seven
    empty rows tells the reader nothing.
    """
    from scheduling.models import ScheduledTask

    days = max(1, min(int(days or SCHEDULE_DAYS), 14))
    today = timezone.now().date()
    end = today + timedelta(days=days)
    start_dt = timezone.make_aware(datetime.combine(today, time.min))
    end_dt = timezone.make_aware(datetime.combine(end, time.min))

    buckets: dict[date, ScheduleDay] = {}

    def bucket_for(day: date) -> ScheduleDay:
        if day not in buckets:
            buckets[day] = ScheduleDay(day=day)
        return buckets[day]

    tasks = ScheduledTask.objects.filter(
        due_date__gte=start_dt, due_date__lt=end_dt,
        status__in=OPEN_TASK_STATUSES,
    )
    if organization is not None:
        tasks = tasks.filter(organization=organization)
    for task in tasks.select_related('organization').order_by('due_date')[:60]:
        bucket_for(task.due_date.date()).items.append({
            'kind': 'task',
            'title': task.title,
            'when': task.due_date,
            'priority': task.priority,
            'context': task.organization.name if task.organization_id else '',
            'icon': 'fa-list-check',
            'url': panel_url('scheduling:task_detail', task.pk),
        })

    try:
        from psa.models import Ticket
        tickets = Ticket.objects.filter(
            resolution_due_at__gte=start_dt, resolution_due_at__lt=end_dt,
        # Ticket.status is a FK to TicketStatus, which carries `is_terminal` —
        # far better than matching status names, which are user-editable.
        ).exclude(status__is_terminal=True)
        if organization is not None:
            tickets = tickets.filter(organization=organization)
        for ticket in tickets.select_related('organization').order_by(
                'resolution_due_at')[:60]:
            bucket_for(ticket.resolution_due_at.date()).items.append({
                'kind': 'ticket',
                'title': f'#{ticket.pk} {ticket.subject}'[:90],
                'when': ticket.resolution_due_at,
                'priority': getattr(ticket, 'priority', 'normal'),
                'context': ticket.organization.name if ticket.organization_id else '',
                'icon': 'fa-ticket',
                'url': panel_url('psa:ticket_detail', ticket.pk),
            })
    except (ImportError, LookupError):
        # PSA is optional in some deployments; a genuinely absent app is fine.
        pass

    for day in buckets.values():
        day.items.sort(key=lambda i: i['when'])
    return [buckets[d] for d in sorted(buckets)]


def get_tasks(user, organization, limit: int = TASK_LIMIT) -> list[TaskRow]:
    """Open work for this user, with expiring items folded in.

    Ordered by due date with undated last, so the top of the list is always the
    most urgent thing rather than the most recently created.
    """
    from scheduling.models import ScheduledTask

    rows: list[TaskRow] = []

    tasks = ScheduledTask.objects.filter(status__in=OPEN_TASK_STATUSES)
    if organization is not None:
        tasks = tasks.filter(organization=organization)
    if user is not None and getattr(user, 'is_authenticated', False):
        # Mine first; the panel is "what do I need to do".
        tasks = tasks.filter(assigned_to=user)
    # Order before slicing. The model's default ordering is by due_date, but
    # SQLite sorts NULLs first ascending — so undated tasks would fill the slice
    # and crowd out the urgent ones the panel exists to show.
    tasks = tasks.select_related('organization').distinct().order_by(
        F('due_date').asc(nulls_last=True), 'priority', 'title')
    for task in tasks[:limit * 2]:
        rows.append(TaskRow(
            kind='task', title=task.title, priority=task.priority,
            due=task.due_date, icon='fa-list-check',
            context=task.organization.name if task.organization_id else '',
            url=panel_url('scheduling:task_detail', task.pk),
        ))

    rows.extend(_expiring_rows(organization))

    def sort_key(row: TaskRow):
        if row.due is None:
            return (1, timezone.now())
        due = row.due
        if not isinstance(due, datetime):
            due = timezone.make_aware(datetime.combine(due, time.min))
        return (0, due_aware(due))

    rows.sort(key=sort_key)
    return rows[:limit]


def _expiring_rows(organization) -> list[TaskRow]:
    """Expiring passwords / tracked expirations / SSL certs as task rows.

    Each queryset is explicitly ordered by its own expiry field before slicing.
    Password defaults to `title` ordering and WebsiteMonitor to `name`, so the
    unordered slice took the alphabetically-first ten rather than the ten
    expiring soonest — the panel would quietly hide the urgent ones.

    The window is bounded at both ends. The panel it replaced showed only
    future expiries (`expires_at__gte=now`); dropping that floor entirely would
    have been worse than keeping it, because these rows sort earliest-first and
    an expiry has no lifecycle a human closes — one record that lapsed years ago
    would sit at the top of Tasks permanently. Recently-lapsed items are still
    real work, so they stay for EXPIRY_GRACE_DAYS with an Overdue badge.

    Only ImportError/LookupError are caught, and deliberately so: an optional
    app being absent is fine, but a coding error must surface rather than
    silently render an empty panel. A broad `except Exception` here is what hid
    `Password.name` (the field is `title`) during development — the panel looked
    like it simply had no data.
    """
    # An aware datetime, not a date: these are all DateTimeFields, and comparing
    # one to a date makes Django coerce it to a naive value and warn.
    now = timezone.now()
    cutoff = now + timedelta(days=EXPIRY_WINDOW_DAYS)
    floor = now - timedelta(days=EXPIRY_GRACE_DAYS)
    rows: list[TaskRow] = []

    try:
        from vault.models import Password
        qs = Password.objects.filter(
            expires_at__gte=floor, expires_at__lte=cutoff)
        if organization is not None:
            qs = qs.filter(organization=organization)
        for pwd in qs.order_by('expires_at')[:10]:
            rows.append(TaskRow(
                kind='password', title=f'Password expires: {pwd.title}',
                due=pwd.expires_at, icon='fa-key', priority='high',
                url=panel_url('vault:password_detail', pwd.pk),
            ))
    except (ImportError, LookupError):
        pass

    try:
        from monitoring.models import Expiration
        qs = Expiration.objects.filter(
            expires_at__gte=floor, expires_at__lte=cutoff)
        if organization is not None:
            qs = qs.filter(organization=organization)
        for exp in qs.order_by('expires_at')[:10]:
            rows.append(TaskRow(
                kind='expiration', title=f'Expiring: {exp.name}',
                due=exp.expires_at, icon='fa-hourglass-half', priority='high',
                url=panel_url('monitoring:expiration_list'),
            ))
    except (ImportError, LookupError):
        pass

    try:
        from monitoring.models import WebsiteMonitor
        qs = WebsiteMonitor.objects.filter(
            ssl_expires_at__gte=floor, ssl_expires_at__lte=cutoff)
        if organization is not None:
            qs = qs.filter(organization=organization)
        for mon in qs.order_by('ssl_expires_at')[:10]:
            rows.append(TaskRow(
                kind='ssl', title=f'SSL expires: {mon.name}',
                due=mon.ssl_expires_at, icon='fa-lock', priority='high',
                url=panel_url('monitoring:website_monitor_detail', mon.pk),
            ))
    except (ImportError, LookupError):
        pass

    return rows
