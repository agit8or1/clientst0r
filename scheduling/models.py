"""
Scheduling models - Scheduled tasks with sign-off support
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager


class ScheduledTask(BaseModel):
    """
    A scheduled recurring or one-time task that requires sign-off from assigned users.
    """
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    RECURRENCE_CHOICES = [
        ('none', 'None (one-time)'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('custom', 'Custom'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
        ('skipped', 'Skipped'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='scheduled_tasks')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    due_date = models.DateTimeField(null=True, blank=True)
    recurrence = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default='none')
    recurrence_interval_days = models.IntegerField(
        null=True, blank=True,
        help_text='Number of days between occurrences (used when recurrence=custom)'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    require_all_signoffs = models.BooleanField(
        default=False,
        help_text='Require all assigned users to sign off before marking complete'
    )
    is_template = models.BooleanField(default=False)
    parent_task = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='child_instances'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_tasks'
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_tasks'
    )
    assigned_to = models.ManyToManyField(
        User, through='TaskAssignment', related_name='assigned_tasks', blank=True
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='scheduled_tasks')

    # PSA ticket linkage (optional)
    psa_ticket = models.ForeignKey(
        'integrations.PSATicket',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scheduled_tasks',
        help_text='Linked PSA/helpdesk ticket (optional)',
    )

    # Alert preferences
    alert_email = models.BooleanField(default=True, help_text='Send email alerts for this task')
    alert_sms = models.BooleanField(default=False, help_text='Send SMS alerts for this task')
    alert_before_hours = models.PositiveIntegerField(
        default=24,
        help_text='Send an alert this many hours before the due date',
    )
    last_alert_sent_at = models.DateTimeField(null=True, blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'scheduling_tasks'
        ordering = ['due_date', 'priority', 'title']
        verbose_name = 'Scheduled Task'
        verbose_name_plural = 'Scheduled Tasks'

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        """True if past due date and not yet completed/cancelled."""
        if self.due_date and self.status in ('pending', 'in_progress'):
            return timezone.now() > self.due_date
        return False

    def get_next_due_date(self):
        """Calculate the next due date based on recurrence setting."""
        if self.recurrence == 'none' or not self.due_date:
            return None
        intervals = {
            'daily': 1,
            'weekly': 7,
            'biweekly': 14,
            'monthly': 30,
            'quarterly': 91,
        }
        if self.recurrence == 'custom':
            days = self.recurrence_interval_days
        else:
            days = intervals.get(self.recurrence)
        if days:
            return self.due_date + timedelta(days=days)
        return None

    def check_completion(self):
        """Check if the task's completion conditions are met and complete it if so."""
        assignments = self.task_assignments.all()
        if not assignments.exists():
            return

        if self.require_all_signoffs:
            completed = all(a.acknowledged for a in assignments)
        else:
            completed = any(a.acknowledged for a in assignments)

        if completed and self.status not in ('completed', 'cancelled'):
            self.status = 'completed'
            self.completed_at = timezone.now()
            self.save()
            if self.recurrence != 'none':
                self.spawn_next_occurrence()

    def spawn_next_occurrence(self):
        """Create the next task instance for recurring tasks."""
        next_due = self.get_next_due_date()
        if not next_due:
            return None

        new_task = ScheduledTask.objects.create(
            organization=self.organization,
            title=self.title,
            description=self.description,
            priority=self.priority,
            due_date=next_due,
            recurrence=self.recurrence,
            recurrence_interval_days=self.recurrence_interval_days,
            status='pending',
            require_all_signoffs=self.require_all_signoffs,
            is_template=False,
            parent_task=self.parent_task if self.parent_task else self,
            created_by=self.created_by,
            psa_ticket=self.psa_ticket,
            alert_email=self.alert_email,
            alert_sms=self.alert_sms,
            alert_before_hours=self.alert_before_hours,
        )

        # Copy tag M2M
        new_task.tags.set(self.tags.all())

        # Copy assignments
        for assignment in self.task_assignments.all():
            TaskAssignment.objects.create(
                task=new_task,
                user=assignment.user,
            )

        return new_task


class TaskAssignment(models.Model):
    """
    Links a user to a scheduled task and tracks their sign-off.
    """
    task = models.ForeignKey(ScheduledTask, on_delete=models.CASCADE, related_name='task_assignments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_assignments')
    acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'scheduling_assignments'
        unique_together = ('task', 'user')
        verbose_name = 'Task Assignment'
        verbose_name_plural = 'Task Assignments'

    def __str__(self):
        return f"{self.user.username} -> {self.task.title}"

    def sign_off(self, notes=''):
        """Record acknowledgement and trigger completion check."""
        self.acknowledged = True
        self.acknowledged_at = timezone.now()
        if notes:
            self.notes = notes
        self.save()
        self.task.check_completion()


class TaskComment(models.Model):
    """
    Comment on a scheduled task.
    """
    task = models.ForeignKey(ScheduledTask, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='task_comments'
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scheduling_comments'
        ordering = ['created_at']
        verbose_name = 'Task Comment'
        verbose_name_plural = 'Task Comments'

    def __str__(self):
        return f"Comment on {self.task.title} by {self.author}"


class SchedulerWallboard(BaseModel):
    """Phase 47 (v3.17.533): a read-only schedule board for a wall-mounted TV.

    Public by design — a shop TV has no keyboard and nobody wants to log a
    display in every morning. That makes the URL itself the only thing standing
    between the schedule and the internet, so:

      * it is off by default (`is_enabled=False`), and a disabled board 404s
        rather than 403s — a 403 confirms the board exists;
      * the address carries a 43-character random token, not the org id, so it
        cannot be guessed or enumerated by walking integers;
      * the token can be rotated, which instantly invalidates any link that has
        leaked;
      * what it shows is opt-in per field. Client names are the most sensitive
        thing on a schedule and can be withheld while keeping the board useful.

    One board per organization. Multiple named boards would be a bigger surface
    and nobody has asked for two.
    """
    # System-wide, not per-organization. In this app an Organization *is* a
    # client, so a per-org board would show one client's jobs — which is not
    # what a screen on the workshop wall is for. One board, every client's work,
    # with `show_client_names` deciding whether the names go up with it.
    is_enabled = models.BooleanField(
        default=False,
        help_text='Off by default. While off, the public URL returns 404.')
    token = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='Random component of the public URL. Rotating it breaks '
                  'every existing link immediately.')

    title = models.CharField(max_length=120, blank=True,
                             help_text='Heading on the board. Defaults to "Schedule".')
    days_ahead = models.PositiveSmallIntegerField(
        default=1,
        help_text='How many days to show, starting today. 1 = today only.')
    refresh_seconds = models.PositiveIntegerField(
        default=60,
        help_text='How often the board reloads itself. Minimum 15.')

    # Each of these adds something to an unauthenticated page, so each is a
    # separate decision rather than one blanket "show details" switch.
    show_client_names = models.BooleanField(
        default=True,
        help_text='Show which client each job is for. Turn off if the screen '
                  'is visible to visitors.')
    show_technician_names = models.BooleanField(default=True)
    show_ticket_numbers = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scheduler_wallboards_created')

    class Meta:
        db_table = 'scheduling_wallboards'

    def __str__(self):
        return f'Scheduler wallboard ({"on" if self.is_enabled else "off"})'

    @classmethod
    def get_board(cls, user=None):
        """The single board, created disabled on first access."""
        board, _created = cls.objects.get_or_create(
            pk=1, defaults={'created_by': user})
        return board

    @staticmethod
    def new_token() -> str:
        """43 URL-safe characters from `secrets` — not `random`, which is
        seeded predictably and has no business generating anything that acts
        as a credential."""
        import secrets
        return secrets.token_urlsafe(32)

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        if not self.token:
            self.token = self.new_token()
        # A board that reloads every second would hammer the server for no
        # human benefit; a wall display is read at walking pace.
        self.refresh_seconds = max(15, int(self.refresh_seconds or 60))
        super().save(*args, **kwargs)

    def rotate_token(self):
        self.token = self.new_token()
        self.save(update_fields=['token', 'updated_at'])
        return self.token

    @property
    def display_title(self) -> str:
        return self.title or 'Schedule'

    def get_public_url(self) -> str:
        from django.urls import reverse
        return reverse('scheduling:wallboard_public', args=[self.token])
