"""
Import models for IT Glue and Hudu data migration
"""
from django.db import models
from django.contrib.auth import get_user_model
from core.models import BaseModel, Organization
from vault.secret_fields import EncryptedTextField

User = get_user_model()


class ImportJob(BaseModel):
    """
    Tracks data import jobs from IT Glue or Hudu.
    """

    SOURCE_CHOICES = [
        ('itglue', 'IT Glue'),
        ('hudu', 'Hudu'),
        ('magicplan', 'MagicPlan Floor Plans'),
        ('csv', 'CSV / Spreadsheet (.csv, .xlsx)'),
    ]

    CSV_TARGET_CHOICES = [
        ('asset', 'Assets'),
        ('password', 'Passwords (Vault)'),
        ('contact', 'Contacts'),
        ('document', 'Documents'),
        # v3.17.523 — spreadsheet import for stock levels.
        ('shop_inventory', 'Shop Inventory'),
        ('vehicle_inventory', 'Vehicle / VAN Inventory'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('completed_with_errors', 'Completed with errors'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('rolled_back', 'Rolled Back'),
        ('partially_rolled_back', 'Partially rolled back'),
    ]

    # A run that finished and wrote what it could.
    SUCCESS_STATUSES = ('completed', 'completed_with_errors')
    # Runs whose surviving ImportMappings point at real imported records -
    # used for duplicate detection and to decide whether rollback is offered.
    ROLLBACK_STATUSES = ('completed', 'completed_with_errors', 'partially_rolled_back')
    DEDUPE_STATUSES = ROLLBACK_STATUSES

    # Source configuration
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    source_url = models.URLField(
        blank=True,
        help_text="API endpoint URL (e.g., https://api.itglue.com or https://demo.hudu.com) - not needed for MagicPlan"
    )
    source_api_key = EncryptedTextField(
        blank=True,
        help_text="API key for authentication - not needed for MagicPlan (encrypted at rest)"
    )

    # File upload (MagicPlan JSON or CSV)
    source_file = models.FileField(
        upload_to='imports/files/%Y/%m/',
        blank=True,
        null=True,
        help_text="Upload file: MagicPlan JSON export, CSV, or .xlsx spreadsheet"
    )

    # CSV field mapper
    csv_target_model = models.CharField(
        max_length=20,
        choices=CSV_TARGET_CHOICES,
        blank=True,
        help_text="What to import CSV rows as (CSV imports only)"
    )
    field_mappings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Maps source column headers to target model field names"
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
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')

    # Rollback tracking
    rolled_back_at = models.DateTimeField(null=True, blank=True, help_text="When this import was rolled back")
    rolled_back_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='import_jobs_rolled_back', help_text="User who rolled back this import")

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

    # Duplicate handling
    skip_duplicates = models.BooleanField(
        default=True,
        help_text="Skip items already imported in any previous job for this organization"
    )

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
        timestamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S %Z')
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

    def reset_counters(self):
        """Zero the per-run counters so a re-run (e.g. of a failed job)
        reports its own numbers instead of adding to the previous attempt's."""
        self.total_items = 0
        self.items_imported = 0
        self.items_skipped = 0
        self.items_failed = 0
        self.error_message = ''
        self.save(update_fields=['total_items', 'items_imported', 'items_skipped',
                                 'items_failed', 'error_message'])

    def finish(self, extra_errors=0):
        """Record the outcome of a run from its real counts.

        * nothing failed                      -> ``completed``
        * some records failed, some got in    -> ``completed_with_errors``
        * records failed and none imported or
          already present (skipped)           -> ``failed``

        ``total_items`` is always imported + skipped + failed, so the numbers on
        the detail page add up. ``extra_errors`` counts problems that are not
        per-record (e.g. an organization that could not be created); they
        downgrade ``completed`` to ``completed_with_errors``.
        """
        from django.utils import timezone
        self.total_items = self.items_imported + self.items_skipped + self.items_failed
        if self.items_failed == 0 and not extra_errors:
            self.status = 'completed'
        elif self.items_failed and self.items_imported == 0 and self.items_skipped == 0:
            self.status = 'failed'
            self.error_message = (
                f"All {self.items_failed} record(s) failed to import - see the log for details."
            )
        else:
            self.status = 'completed_with_errors'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'error_message', 'total_items',
                                 'items_imported', 'items_skipped', 'items_failed'])
        return self.status

    @property
    def is_finished_successfully(self):
        return self.status in self.SUCCESS_STATUSES

    def can_rollback(self):
        """Check if this import can be rolled back.

        Allowed for any real (non-dry-run) run that may have written data:
        completed, completed with errors, a previous partial rollback, or a
        failed run that nonetheless created some records.
        """
        if self.rolled_back_at or self.dry_run:
            return False
        if self.status in self.ROLLBACK_STATUSES:
            return True
        if self.status == 'failed' and self.pk:
            return self.mappings.exists()
        return False

    def rollback(self, user):
        """
        Roll back this import. See ``imports.rollback.rollback_import`` for the
        rules (records edited after the import are kept and reported, created
        organizations are removed only when nothing else references them, and
        the job is marked ``rolled_back`` only when everything was handled).

        Returns:
            dict: rollback report
        """
        if not self.can_rollback():
            raise ValueError(f"Cannot rollback import {self.id}: status={self.status}, rolled_back={bool(self.rolled_back_at)}, dry_run={self.dry_run}")
        from imports.rollback import rollback_import
        return rollback_import(self, user)


# Every model an importer can create, keyed by the ``target_model`` string stored
# on ImportMapping. Rollback and duplicate detection resolve through this.
IMPORT_TARGET_MODELS = {
    'Asset': ('assets', 'Asset'),
    'Contact': ('assets', 'Contact'),
    'Password': ('vault', 'Password'),
    'Document': ('docs', 'Document'),
    'Organization': ('core', 'Organization'),
    'Location': ('locations', 'Location'),
    'LocationFloorPlan': ('locations', 'LocationFloorPlan'),
    # Legacy alias: older rollback code referred to floor plans as 'FloorPlan'.
    'FloorPlan': ('locations', 'LocationFloorPlan'),
    'ShopInventoryItem': ('vehicles', 'ShopInventoryItem'),
    'VehicleInventoryItem': ('vehicles', 'VehicleInventoryItem'),
}


def resolve_target_model(name):
    """Return the model class for an ImportMapping.target_model, or None."""
    from django.apps import apps
    spec = IMPORT_TARGET_MODELS.get(name)
    if not spec:
        return None
    try:
        return apps.get_model(*spec)
    except LookupError:
        return None


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
    target_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Target's updated_at right after the import wrote it. Rollback keeps "
                  "records modified after this instead of deleting them.",
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

    def target_exists(self):
        Model = resolve_target_model(self.target_model)
        if Model is None:
            return True  # unknown type: assume it is still there (conservative)
        return Model._base_manager.filter(pk=self.target_id).exists()
