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
        ('magicplan', 'MagicPlan Floor Plans'),
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
    source_url = models.URLField(
        blank=True,
        help_text="API endpoint URL (e.g., https://api.itglue.com or https://demo.hudu.com) - not needed for MagicPlan"
    )
    source_api_key = models.CharField(
        max_length=500,
        blank=True,
        help_text="API key for authentication - not needed for MagicPlan"
    )

    # MagicPlan file upload
    source_file = models.FileField(
        upload_to='imports/magicplan/%Y/%m/',
        blank=True,
        null=True,
        help_text="MagicPlan JSON export file"
    )

    # Import settings (optional - if null, imports all organizations from source)
    target_organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='import_jobs',
        null=True,
        blank=True,
        help_text="Optional: Import into specific organization. Leave blank to import all organizations from source."
    )

    # Floor plan import settings
    target_location = models.ForeignKey(
        'locations.Location',
        on_delete=models.CASCADE,
        related_name='import_jobs',
        null=True,
        blank=True,
        help_text="Optional: Link floor plans to existing location. Leave blank to create new location from MagicPlan data."
    )

    # Organization matching settings
    use_fuzzy_matching = models.BooleanField(
        default=True,
        help_text="Use fuzzy matching to find existing organizations with similar names"
    )
    fuzzy_match_threshold = models.IntegerField(
        default=85,
        help_text="Similarity threshold for fuzzy matching (0-100, default 85)"
    )

    # Organization import tracking
    organizations_created = models.PositiveIntegerField(
        default=0,
        help_text="Number of organizations created during import"
    )
    organizations_matched = models.PositiveIntegerField(
        default=0,
        help_text="Number of organizations matched to existing"
    )

    # What to import
    import_assets = models.BooleanField(default=True, help_text="Import assets/configuration items")
    import_passwords = models.BooleanField(default=True, help_text="Import passwords")
    import_documents = models.BooleanField(default=True, help_text="Import documents/articles")
    import_contacts = models.BooleanField(default=False, help_text="Import contacts")
    import_locations = models.BooleanField(default=False, help_text="Import locations")
    import_networks = models.BooleanField(default=False, help_text="Import networks")
    import_floor_plans = models.BooleanField(default=True, help_text="Import floor plans (MagicPlan only)")

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
    floor_plans_imported = models.PositiveIntegerField(default=0, help_text="Number of floor plans imported (MagicPlan)")

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
        target = self.target_organization.name if self.target_organization else "All Organizations"
        return f"{self.get_source_type_display()} import to {target} - {self.get_status_display()}"

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


class OrganizationMapping(BaseModel):
    """
    Tracks mappings between source organizations/companies and Client St0r organizations.
    """

    import_job = models.ForeignKey(
        ImportJob,
        on_delete=models.CASCADE,
        related_name='organization_mappings'
    )

    # Source organization
    source_id = models.CharField(max_length=100, help_text="Organization ID in source system")
    source_name = models.CharField(max_length=255, help_text="Organization name in source system")

    # Target organization
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='import_mappings'
    )

    # Matching info
    was_created = models.BooleanField(default=False, help_text="True if organization was created, False if matched")
    match_score = models.IntegerField(null=True, blank=True, help_text="Fuzzy match score (0-100) if matched")

    class Meta:
        db_table = 'organization_mappings'
        unique_together = [['import_job', 'source_id']]
        indexes = [
            models.Index(fields=['source_id']),
            models.Index(fields=['organization']),
        ]

    def __str__(self):
        action = "created" if self.was_created else f"matched ({self.match_score}%)"
        return f"{self.source_name} -> {self.organization.name} ({action})"


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
    source_organization_id = models.CharField(max_length=100, blank=True, help_text="Source organization ID for this object")

    # Target object
    target_model = models.CharField(max_length=100, help_text="Django model name (Asset, Password, etc.)")
    target_id = models.PositiveIntegerField(help_text="ID in Client St0r")
    target_organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Organization this object belongs to"
    )

    class Meta:
        db_table = 'import_mappings'
        unique_together = [['import_job', 'source_type', 'source_id']]
        indexes = [
            models.Index(fields=['source_type', 'source_id']),
            models.Index(fields=['target_model', 'target_id']),
            models.Index(fields=['source_organization_id']),
        ]

    def __str__(self):
        return f"{self.source_type} {self.source_id} -> {self.target_model} {self.target_id}"
