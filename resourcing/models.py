"""
Resource-management models — Phase 2.1 + Phase 2.2.

Cross-cuts accounts (User), psa, and core, so this lives in its own app
to avoid circular imports and to keep migration ownership clean.

Phase 2.1 models:
  * UserSkill          — what techs are good at (proficiency tiers)
  * UserCertification  — credentials with optional expiry tracking
  * WorkingHours       — per-weekday availability windows

Phase 2.2 models:
  * Holiday            — org-scoped or global non-working days
  * LeaveRequest       — PTO with approval workflow
  * BillableTarget     — per-tech weekly billable-hours goal

Plus a `working_days_in_period` helper used by Phase 3 capacity reporting
and Phase 8.5 GPS off-shift suppression.
"""
from django.conf import settings as django_settings
from django.db import models


class UserSkill(models.Model):
    PROFICIENCY = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ]
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='resourcing_skills',
    )
    name = models.CharField(max_length=120)
    proficiency = models.CharField(max_length=20, choices=PROFICIENCY, default='intermediate')
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_user_skills'
        unique_together = [['user', 'name']]
        ordering = ['name']

    def __str__(self):
        return f'{self.user.username}: {self.name} ({self.get_proficiency_display()})'


class UserCertification(models.Model):
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='resourcing_certifications',
    )
    name = models.CharField(
        max_length=200,
        help_text='e.g. "Microsoft 365 Certified: Modern Desktop Administrator"',
    )
    issuer = models.CharField(
        max_length=120,
        blank=True,
        help_text='e.g. Microsoft, Cisco, CompTIA, AWS',
    )
    credential_id = models.CharField(max_length=120, blank=True)
    issued_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(
        null=True, blank=True,
        help_text='Leave blank if no expiry.',
    )
    verification_url = models.URLField(blank=True)
    attachment = models.FileField(
        upload_to='certifications/%Y/%m/', null=True, blank=True,
        help_text='PDF or image of the certificate.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_user_certifications'
        ordering = ['-issued_at', 'name']

    def __str__(self):
        return f'{self.user.username}: {self.name}'

    @property
    def is_expired(self):
        from django.utils import timezone
        return self.expires_at is not None and self.expires_at < timezone.localdate()

    @property
    def expires_soon(self):
        """True if expires within the next 60 days (and not already expired)."""
        from datetime import timedelta
        from django.utils import timezone
        if not self.expires_at:
            return False
        today = timezone.localdate()
        return today <= self.expires_at <= today + timedelta(days=60)


class WorkingHours(models.Model):
    """
    A user's working window for a specific weekday. Multiple rows per
    weekday allowed (split shifts: 9-12, 13-17). Times are in the user's
    profile timezone (UserProfile.timezone) — capacity reporting + GPS
    off-shift suppression normalize to UTC at query time.
    """
    WEEKDAYS = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'),
        (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='resourcing_working_hours',
    )
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_working_hours'
        ordering = ['user', 'weekday', 'start_time']

    def __str__(self):
        return f'{self.user.username} {self.get_weekday_display()} {self.start_time}–{self.end_time}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.end_time <= self.start_time:
            raise ValidationError({'end_time': 'End time must be after start time.'})


# ---------------------------------------------------------------------------
# Phase 2.2 — Holiday + LeaveRequest + BillableTarget
# ---------------------------------------------------------------------------


class Holiday(models.Model):
    """Org-wide non-working day. Used by capacity reporting (subtracts
    from available hours) and the off-shift suppression query for
    GPS auto-time (Phase 8.5)."""
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='resourcing_holidays',
        null=True, blank=True,
        help_text='NULL = applies to every org (e.g. national holidays).',
    )
    name = models.CharField(max_length=120)
    date = models.DateField()
    is_recurring_yearly = models.BooleanField(
        default=False,
        help_text='If true, the date applies every year (only month + day matter).',
    )
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_holidays'
        ordering = ['date', 'name']
        indexes = [models.Index(fields=['organization', 'date'])]

    def __str__(self):
        return f'{self.name} ({self.date})'

    @classmethod
    def is_holiday(cls, target_date, organization=None):
        """True if target_date is a holiday for `organization` (or any
        global holiday). Honors yearly recurrence."""
        from django.db.models import Q
        qs = cls.objects.filter(
            Q(organization__isnull=True) | Q(organization=organization)
        )
        # Exact date match
        if qs.filter(date=target_date, is_recurring_yearly=False).exists():
            return True
        # Recurring yearly — match month+day only
        if qs.filter(
            is_recurring_yearly=True,
            date__month=target_date.month,
            date__day=target_date.day,
        ).exists():
            return True
        return False


class LeaveRequest(models.Model):
    LEAVE_TYPES = [
        ('vacation', 'Vacation'),
        ('sick', 'Sick Leave'),
        ('personal', 'Personal Day'),
        ('bereavement', 'Bereavement'),
        ('jury_duty', 'Jury Duty'),
        ('parental', 'Parental Leave'),
        ('unpaid', 'Unpaid Leave'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='resourcing_leave_requests',
    )
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPES, default='vacation')
    start_date = models.DateField()
    end_date = models.DateField()
    is_half_day = models.BooleanField(
        default=False,
        help_text='Half-day flag — only meaningful when start_date == end_date.',
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    approver = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_leave_requests'
        ordering = ['-start_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f'{self.user.username} — {self.get_leave_type_display()} {self.start_date}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date must be on or after start date.'})

    @property
    def total_days(self):
        if self.is_half_day and self.start_date == self.end_date:
            return 0.5
        return (self.end_date - self.start_date).days + 1

    @classmethod
    def is_user_on_leave(cls, user, target_date):
        """True if `user` has an approved leave covering `target_date`."""
        return cls.objects.filter(
            user=user, status='approved',
            start_date__lte=target_date, end_date__gte=target_date,
        ).exists()


class BillableTarget(models.Model):
    """Per-tech weekly billable-hours target. Used by Phase 3 utilization
    reporting: actual_billable_hours / target_hours_per_week → % utilization."""
    user = models.OneToOneField(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='resourcing_billable_target',
    )
    target_hours_per_week = models.DecimalField(
        max_digits=5, decimal_places=2, default=32,
        help_text='Hours per week the tech should bill against client work.',
    )
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_billable_targets'

    def __str__(self):
        return f'{self.user.username}: {self.target_hours_per_week}h/wk'


class TechCostRate(models.Model):
    """
    Loaded cost rate per tech ($/hr) used by Phase 3 profitability
    reports. Effective-dated so historical reports stay accurate after
    a raise / role change.
    """
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='resourcing_cost_rates',
    )
    rate_per_hour = models.DecimalField(max_digits=8, decimal_places=2)
    effective_from = models.DateField(
        help_text='Rate applies from this date forward (inclusive). The '
                  'most recent effective_from <= a given report date wins.',
    )
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_tech_cost_rates'
        ordering = ['-effective_from', 'user__username']
        unique_together = [['user', 'effective_from']]
        indexes = [models.Index(fields=['user', '-effective_from'])]

    def __str__(self):
        return f'{self.user.username}: ${self.rate_per_hour}/hr from {self.effective_from}'

    @classmethod
    def rate_for(cls, user, target_date):
        """Best-matching rate for `user` on `target_date`. Returns Decimal
        (or DEFAULT_LOADED_RATE if no rate is configured)."""
        from decimal import Decimal
        row = cls.objects.filter(
            user=user, effective_from__lte=target_date
        ).order_by('-effective_from').first()
        if row:
            return row.rate_per_hour
        # Fallback to canonical default; import locally to dodge cycle
        from reports.queries import DEFAULT_LOADED_RATE
        return Decimal(str(DEFAULT_LOADED_RATE))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def working_days_in_period(user, start_date, end_date, organization=None):
    """Count working days for `user` in [start_date, end_date], excluding:
    - Days the user has no WorkingHours for that weekday
    - Org or global holidays
    - Approved leave requests
    Used by Phase 3 capacity reporting + Phase 8.5 off-shift suppression."""
    from datetime import timedelta
    days = 0
    cur = start_date
    any_whs = user.resourcing_working_hours.exists()
    while cur <= end_date:
        weekday = cur.weekday()
        # Skip if no working hours configured for this weekday (and the user
        # has any working hours at all — backwards-compat with v3.17.132)
        whs = user.resourcing_working_hours.filter(weekday=weekday, is_active=True)
        if any_whs and not whs.exists():
            cur += timedelta(days=1); continue
        # Skip holidays
        if Holiday.is_holiday(cur, organization=organization):
            cur += timedelta(days=1); continue
        # Skip approved leave
        if LeaveRequest.is_user_on_leave(user, cur):
            cur += timedelta(days=1); continue
        days += 1
        cur += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Phase 11 — shift templates + weekly shift schedule
# ---------------------------------------------------------------------------


class ShiftTemplate(models.Model):
    """A reusable shift: "Early 07:00–15:00", "Night on-call 22:00–06:00".

    Times are wall-clock times in each technician's profile time zone (the
    same rule as WorkingHours). An end at or before the start runs past
    midnight into the next day. `is_on_call` shifts make the technician on
    call for routing while they run.
    """
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField(help_text='At or before the start = ends the next day.')
    is_on_call = models.BooleanField(
        default=False, help_text='Technicians on this shift count as on call for ticket routing.')
    color = models.CharField(max_length=20, blank=True, default='',
                             help_text='Optional CSS colour for the schedule, e.g. #0d6efd.')
    notes = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'resourcing_shift_templates'
        ordering = ['start_time', 'name']

    def __str__(self):
        return f'{self.name} {self.start_time:%H:%M}–{self.end_time:%H:%M}'

    @property
    def overnight(self):
        return self.end_time <= self.start_time

    @property
    def duration_minutes(self):
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return (end - start) % (24 * 60) or 24 * 60

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.color and not all(ch.isalnum() or ch == '#' for ch in self.color):
            raise ValidationError({'color': 'Use a colour name or a #hex value.'})


class ShiftAssignment(models.Model):
    """A template worked on some weekdays by one technician or by a whole team
    (auth.Group), from `effective_from` until `effective_until` (blank = no
    end). Dispatch, on-call and routing availability read the schedule through
    resourcing/shifts.py."""
    template = models.ForeignKey(ShiftTemplate, on_delete=models.CASCADE, related_name='assignments')
    user = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             null=True, blank=True, related_name='resourcing_shift_assignments')
    team = models.ForeignKey('auth.Group', on_delete=models.CASCADE, null=True, blank=True,
                             related_name='resourcing_shift_assignments')
    weekdays = models.JSONField(default=list, help_text='0=Monday .. 6=Sunday')
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'resourcing_shift_assignments'
        ordering = ['effective_from', 'pk']
        indexes = [models.Index(fields=['user', 'effective_from']),
                   models.Index(fields=['team', 'effective_from'])]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(user__isnull=False, team__isnull=True)
                           | models.Q(user__isnull=True, team__isnull=False)),
                name='resourcing_shift_user_xor_team'),
        ]

    def __str__(self):
        who = self.user.get_username() if self.user_id else f'team {self.team}'
        return f'{who}: {self.template} on {self.weekday_labels}'

    @property
    def weekday_labels(self):
        names = dict(WorkingHours.WEEKDAYS)
        return ', '.join(names.get(int(d), '?')[:3] for d in sorted(self.weekdays or []))

    def covers(self, day):
        if day < self.effective_from:
            return False
        if self.effective_until and day > self.effective_until:
            return False
        return day.weekday() in {int(d) for d in (self.weekdays or [])}

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.user_id) == bool(self.team_id):
            raise ValidationError('Choose a technician or a team.')
        if not self.weekdays:
            raise ValidationError({'weekdays': 'Pick at least one weekday.'})
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({'effective_until': 'The end date must be on or after the start date.'})
