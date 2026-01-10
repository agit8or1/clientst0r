"""
Runbook/SOP models - Standard Operating Procedures
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager


class Runbook(BaseModel):
    """
    Runbook/SOP with sequential steps.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='runbooks')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)

    # Categorization
    category = models.ForeignKey('docs.DocumentCategory', on_delete=models.SET_NULL, null=True, blank=True, related_name='runbooks')
    tags = models.ManyToManyField(Tag, blank=True, related_name='runbooks')

    # Metadata
    estimated_duration = models.IntegerField(null=True, blank=True, help_text='Estimated duration in minutes')
    difficulty = models.CharField(max_length=20, choices=[
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ], default='intermediate')

    is_published = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)

    # Versioning
    version = models.CharField(max_length=50, default='1.0')
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    review_frequency_days = models.IntegerField(null=True, blank=True, help_text='How often to review (days)')

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='runbooks_created')
    last_modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='runbooks_modified')

    objects = OrganizationManager()

    class Meta:
        db_table = 'runbooks'
        unique_together = [['organization', 'slug']]
        ordering = ['title']
        indexes = [
            models.Index(fields=['organization', 'is_published']),
        ]

    def __str__(self):
        return self.title

    @property
    def needs_review(self):
        """Check if runbook needs review."""
        if not self.last_reviewed_at or not self.review_frequency_days:
            return False
        from django.utils import timezone
        from datetime import timedelta
        next_review = self.last_reviewed_at + timedelta(days=self.review_frequency_days)
        return timezone.now() > next_review


class RunbookStep(BaseModel):
    """
    Individual step in a runbook.
    """
    runbook = models.ForeignKey(Runbook, on_delete=models.CASCADE, related_name='steps')
    order = models.IntegerField()
    title = models.CharField(max_length=255)
    description = models.TextField(help_text='Step instructions')

    # Optional: Expected result
    expected_result = models.TextField(blank=True)

    # Optional: Code snippet or command
    code_snippet = models.TextField(blank=True)
    code_language = models.CharField(max_length=50, blank=True, help_text='e.g., bash, python, sql')

    # Optional: Screenshot/image reference
    has_screenshot = models.BooleanField(default=False)

    # Warnings
    is_critical = models.BooleanField(default=False, help_text='Mark step as critical/dangerous')
    warning_text = models.TextField(blank=True, help_text='Warning message for critical steps')

    class Meta:
        db_table = 'runbook_steps'
        ordering = ['order']
        unique_together = [['runbook', 'order']]

    def __str__(self):
        return f"{self.runbook.title} - Step {self.order}: {self.title}"


class RunbookExecution(BaseModel):
    """
    Track runbook executions.
    """
    runbook = models.ForeignKey(Runbook, on_delete=models.CASCADE, related_name='executions')
    executed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='runbook_executions')

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=[
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('abandoned', 'Abandoned'),
    ], default='in_progress')

    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'runbook_executions'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.runbook.title} executed by {self.executed_by} on {self.started_at}"

    @property
    def duration(self):
        """Calculate execution duration."""
        if not self.completed_at:
            return None
        return self.completed_at - self.started_at


class RunbookStepCompletion(models.Model):
    """
    Track completion of individual steps during execution.
    """
    execution = models.ForeignKey(RunbookExecution, on_delete=models.CASCADE, related_name='step_completions')
    step = models.ForeignKey(RunbookStep, on_delete=models.CASCADE)

    completed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    success = models.BooleanField(default=True)

    class Meta:
        db_table = 'runbook_step_completions'
        unique_together = [['execution', 'step']]
        ordering = ['completed_at']

    def __str__(self):
        return f"Step {self.step.order} - {'Success' if self.success else 'Failed'}"
