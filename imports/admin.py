"""
Django admin configuration for imports app
"""
from django.contrib import admin
from .models import ImportJob, ImportMapping


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    """Admin interface for import jobs."""

    list_display = ['id', 'source_type', 'target_organization', 'status', 'dry_run', 'items_imported', 'items_failed', 'created_at']
    list_filter = ['source_type', 'status', 'dry_run', 'created_at']
    search_fields = ['target_organization__name', 'source_url']
    readonly_fields = ['started_at', 'completed_at', 'items_imported', 'items_skipped', 'items_failed', 'total_items', 'import_log', 'error_message']

    fieldsets = [
        ('Source Configuration', {
            'fields': ['source_type', 'source_url', 'source_api_key']
        }),
        ('Import Settings', {
            'fields': ['target_organization', 'import_assets', 'import_passwords', 'import_documents', 'import_contacts', 'import_locations', 'import_networks', 'dry_run']
        }),
        ('Execution', {
            'fields': ['status', 'started_by', 'started_at', 'completed_at']
        }),
        ('Results', {
            'fields': ['total_items', 'items_imported', 'items_skipped', 'items_failed', 'error_message']
        }),
        ('Log', {
            'fields': ['import_log'],
            'classes': ['collapse']
        }),
    ]


@admin.register(ImportMapping)
class ImportMappingAdmin(admin.ModelAdmin):
    """Admin interface for import mappings."""

    list_display = ['id', 'import_job', 'source_type', 'source_id', 'target_model', 'target_id']
    list_filter = ['source_type', 'target_model']
    search_fields = ['source_id', 'target_id']
    readonly_fields = ['import_job', 'source_type', 'source_id', 'target_model', 'target_id']
