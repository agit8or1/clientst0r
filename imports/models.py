"""
Import models for IT Glue and Hudu data migration
"""
from django.db import models
from django.contrib.auth import get_user_model
from core.models import BaseModel, Organization

User = get_user_model()


class ImportJob(BaseModel):
    """
    Tracks data import jobs from IT Glue or Hudu.
    """

    SOURCE_CHOICES = [
        ('itglue', 'IT Glue'),
        ('hudu', 'Hudu'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    # Source configuration
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    source_url = models.URLField(help_text="API endpoint URL (e.g., https://api.itglue.com or https://demo.hudu.com)")
    source_api_key = models.CharField(max_length=500, help_text="API key for authentication")

    # Import settings
    target_organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='import_jobs',
        help_text="Organization to import data into"
    )

    # What to import
    import_assets = models.BooleanField(default=True, help_text="Import assets/configuration items")
    import_passwords = models.BooleanField(default=True, help_text="Import passwords")
    import_documents = models.BooleanField(default=True, help_text="Import documents/articles")
    import_contacts = models.BooleanField(default=False, help_text="Import contacts")
    import_locations = models.BooleanField(default=False, help_text="Import locations")
    import_networks = models.BooleanField(default=False, help_text="Import networks")

    # Execution tracking
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='import_jobs_started')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Results
    total_items = models.PositiveIntegerField(default=0, help_text="Total items to import")
    items_imported = models.PositiveIntegerField(default=0, help_text="Successfully imported items")
    items_skipped = models.PositiveIntegerField(default=0, help_text="Skipped items (already exist)")
    items_failed = models.PositiveIntegerField(default=0, help_text="Failed items")

    error_message = models.TextField(blank=True, help_text="Error message if failed")
    import_log = models.TextField(blank=True, help_text="Detailed import log")

    # Dry run mode
    dry_run = models.BooleanField(default=True, help_text="Preview import without saving data")

    class Meta:
        db_table = 'import_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['source_type']),
            models.Index(fields=['target_organization']),
        ]

    def __str__(self):
        return f"{self.get_source_type_display()} import to {self.target_organization.name} - {self.get_status_display()}"

    def add_log(self, message):
        """Add a message to the import log."""
        from django.utils import timezone
        timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        self.import_log += f"[{timestamp}] {message}\n"
        self.save(update_fields=['import_log'])

    def mark_running(self):
        """Mark job as running."""
        from django.utils import timezone
        self.status = 'running'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])

    def mark_completed(self):
        """Mark job as completed."""
        from django.utils import timezone
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])

    def mark_failed(self, error_message):
        """Mark job as failed."""
        from django.utils import timezone
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.save(update_fields=['status', 'completed_at', 'error_message'])


class ImportMapping(BaseModel):
    """
    Tracks mappings between source IDs and imported objects.
    Used to prevent duplicate imports.
    """

    import_job = models.ForeignKey(
        ImportJob,
        on_delete=models.CASCADE,
        related_name='mappings'
    )

    # Source object
    source_type = models.CharField(max_length=50, help_text="Source object type (asset, password, document, etc.)")
    source_id = models.CharField(max_length=100, help_text="ID in source system")

    # Target object
    target_model = models.CharField(max_length=100, help_text="Django model name (Asset, Password, etc.)")
    target_id = models.PositiveIntegerField(help_text="ID in HuduGlue")

    class Meta:
        db_table = 'import_mappings'
        unique_together = [['import_job', 'source_type', 'source_id']]
        indexes = [
            models.Index(fields=['source_type', 'source_id']),
            models.Index(fields=['target_model', 'target_id']),
        ]

    def __str__(self):
        return f"{self.source_type} {self.source_id} -> {self.target_model} {self.target_id}"
