"""
Processes and Diagrams models
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager


class Process(BaseModel):
    """
    Process/runbook defining a sequential workflow.
    Can be global (superuser-created) or org-specific.
    """
    CATEGORY_CHOICES = [
        ('onboarding', 'User Onboarding'),
        ('offboarding', 'User Offboarding'),
        ('client_onboarding', 'Client Onboarding'),
        ('client_offboarding', 'Client Offboarding'),
        ('client_termination', 'Client Termination'),
        ('deployment', 'System Deployment'),
        ('maintenance', 'Maintenance'),
        ('incident', 'Incident Response'),
        ('backup', 'Backup/Recovery'),
        ('security', 'Security Audit'),
        ('change', 'Change Management'),
        ('other', 'Other'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='processes'
    )

    # Core fields
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)

    # Global vs org-specific (follows Document pattern)
    is_global = models.BooleanField(
        default=False,
        help_text='Global process - visible to all organizations'
    )
    is_published = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    is_template = models.BooleanField(
        default=False,
        help_text='Process template - can be cloned by organizations'
    )

    # Categorization
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default='other'
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='processes')

    # Optional diagram link (diagrams are in docs app)
    linked_diagram = models.ForeignKey(
        'docs.Diagram',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processes',
        help_text='Link to a diagram for visual representation'
    )

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processes_created'
    )
    last_modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processes_modified'
    )

    objects = OrganizationManager()

    class Meta:
        db_table = 'processes'
        unique_together = [['organization', 'slug']]
        ordering = ['title']
        verbose_name = 'Workflow'
        verbose_name_plural = 'Workflows'
        indexes = [
            models.Index(fields=['organization', 'slug']),
            models.Index(fields=['is_global', 'is_published']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        prefix = "[GLOBAL] " if self.is_global else ""
        template = "[TEMPLATE] " if self.is_template else ""
        return f"{prefix}{template}{self.title}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)


class ProcessStage(BaseModel):
    """
    Individual stage/step in a process.
    Can optionally link to ONE entity (document, password, secure note, or asset).
    """
    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='stages'
    )

    # Stage content
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        help_text='Detailed instructions for this stage'
    )

    # Entity linking - nullable ForeignKeys (ONE is allowed)
    linked_document = models.ForeignKey(
        'docs.Document',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='process_stages',
        help_text='Related knowledge base document'
    )
    linked_password = models.ForeignKey(
        'vault.Password',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='process_stages',
        help_text='Related password/credential'
    )
    linked_secure_note = models.ForeignKey(
        'core.SecureNote',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='process_stages',
        help_text='Related secure note'
    )
    linked_asset = models.ForeignKey(
        'assets.Asset',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='process_stages',
        help_text='Related asset'
    )

    # Optional: Require completion confirmation
    requires_confirmation = models.BooleanField(
        default=False,
        help_text='Stage requires user to confirm completion'
    )
    estimated_duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Estimated time to complete (minutes)'
    )

    class Meta:
        db_table = 'process_stages'
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['process', 'order']),
        ]

    def __str__(self):
        return f"{self.process.title} - Stage {self.order}: {self.title}"

    def clean(self):
        """Validate that only ONE entity is linked."""
        linked_count = sum([
            bool(self.linked_document),
            bool(self.linked_password),
            bool(self.linked_secure_note),
            bool(self.linked_asset),
        ])
        if linked_count > 1:
            raise ValidationError(
                "A stage can only link to ONE entity at a time."
            )

    def get_linked_entity(self):
        """Return the linked entity (if any) and its type."""
        if self.linked_document:
            return ('document', self.linked_document)
        elif self.linked_password:
            return ('password', self.linked_password)
        elif self.linked_secure_note:
            return ('secure_note', self.linked_secure_note)
        elif self.linked_asset:
            return ('asset', self.linked_asset)
        return (None, None)


class ProcessExecution(BaseModel):
    """
    Tracks execution/running of a process.
    Records who is executing it and completion status.
    """
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='executions'
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='process_executions'
    )

    # Who is executing
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='assigned_process_executions'
    )
    started_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='started_process_executions'
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='not_started'
    )

    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)

    # Notes
    notes = models.TextField(blank=True)

    # PSA ticket linking — third-party external PSA (Halo/Autotask/etc.)
    psa_ticket = models.ForeignKey(
        'integrations.PSATicket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='process_executions',
        help_text='Related external (third-party) PSA ticket for this execution'
    )
    # Native PSA ticket linking — runs against the in-house PSA module
    native_psa_ticket = models.ForeignKey(
        'psa.Ticket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='process_executions',
        help_text='Related native PSA ticket — set when a tech launches the workflow from the ticket detail page'
    )
    psa_note_internal = models.BooleanField(
        default=False,
        help_text='Make PSA ticket note internal/private (not visible to customer)'
    )

    objects = OrganizationManager()

    class Meta:
        db_table = 'process_executions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', '-created_at']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['process', 'status']),
        ]

    def __str__(self):
        return f"{self.process.title} - {self.assigned_to.username} ({self.status})"

    @property
    def completion_percentage(self):
        """Calculate percentage of completed stages."""
        total_stages = self.process.stages.count()
        if total_stages == 0:
            return 0
        completed_stages = self.stage_completions.filter(is_completed=True).count()
        return int((completed_stages / total_stages) * 100)

    @property
    def is_overdue(self):
        """Check if execution is past due date."""
        if not self.due_date:
            return False
        from django.utils import timezone
        return timezone.now() > self.due_date and self.status != 'completed'


class ProcessStageCompletion(BaseModel):
    """
    Tracks completion of individual stages within a process execution.
    """
    execution = models.ForeignKey(
        ProcessExecution,
        on_delete=models.CASCADE,
        related_name='stage_completions'
    )
    stage = models.ForeignKey(
        ProcessStage,
        on_delete=models.CASCADE,
        related_name='completions'
    )

    is_completed = models.BooleanField(default=False)
    completed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    spawned_ticket = models.ForeignKey(
        'psa.Ticket',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='spawned_from_stage_completions',
        help_text='PSA ticket created from this stage via the runbook-to-ticket flow.',
    )

    class Meta:
        db_table = 'process_stage_completions'
        unique_together = [['execution', 'stage']]
        ordering = ['stage__order']
        indexes = [
            models.Index(fields=['execution', 'is_completed']),
        ]

    def __str__(self):
        status = "✓" if self.is_completed else "○"
        return f"{status} {self.stage.title}"


class ProcessExecutionAuditLog(BaseModel):
    """
    Audit log for process execution activities.
    Tracks every action/change during workflow execution.
    """
    ACTION_TYPES = [
        ('execution_created', 'Execution Created'),
        ('execution_started', 'Execution Started'),
        ('execution_assigned', 'Execution Assigned'),
        ('execution_status_changed', 'Status Changed'),
        ('execution_completed', 'Execution Completed'),
        ('execution_failed', 'Execution Failed'),
        ('execution_cancelled', 'Execution Cancelled'),
        ('stage_completed', 'Stage Completed'),
        ('stage_uncompleted', 'Stage Uncompleted'),
        ('stage_notes_added', 'Stage Notes Added'),
        ('notes_updated', 'Execution Notes Updated'),
        ('due_date_changed', 'Due Date Changed'),
    ]

    # Link to execution
    execution = models.ForeignKey(
        ProcessExecution,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )

    # Action details
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    description = models.TextField(help_text='Human-readable description of the action')

    # Who performed the action
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='process_execution_audit_logs'
    )
    username = models.CharField(max_length=150, help_text='Username stored for history')

    # For stage-specific actions
    stage = models.ForeignKey(
        ProcessStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        help_text='Related stage (if action is stage-specific)'
    )
    stage_title = models.CharField(
        max_length=255,
        blank=True,
        help_text='Stage title stored for history'
    )

    # Change tracking
    old_value = models.JSONField(
        null=True,
        blank=True,
        help_text='Previous value (for updates)'
    )
    new_value = models.JSONField(
        null=True,
        blank=True,
        help_text='New value (for updates)'
    )

    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        db_table = 'process_execution_audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['execution', '-created_at']),
            models.Index(fields=['action_type', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.username} - {self.get_action_type_display()} - {self.execution}"

    @classmethod
    def log_action(cls, execution, action_type, user, description,
                   stage=None, old_value=None, new_value=None,
                   request=None):
        """Helper method to create audit log entries."""
        # Get IP and user agent from request if provided
        ip_address = None
        user_agent = ''
        if request:
            from core.client_ip import get_client_ip
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        # Create process-specific audit log
        audit_log = cls.objects.create(
            execution=execution,
            action_type=action_type,
            description=description,
            user=user,
            username=user.username if user else 'System',
            stage=stage,
            stage_title=stage.title if stage else '',
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            user_agent=user_agent
        )

        # Also log to general audit system for system-wide tracking
        from audit.models import AuditLog
        AuditLog.log(
            user=user,
            action='update',
            organization=execution.organization,
            object_type='process_execution',
            object_id=execution.id,
            object_repr=str(execution),
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            extra_data={
                'action_type': action_type,
                'stage_id': stage.id if stage else None,
                'stage_title': stage.title if stage else None,
            }
        )

        return audit_log
