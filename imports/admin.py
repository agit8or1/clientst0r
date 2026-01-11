"""
Django admin configuration for imports app
"""
from django.contrib import admin
from .models import ImportJob, ImportMapping, OrganizationMapping


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    """Admin interface for import jobs."""

    list_display = ['id', 'source_type', 'target_organization', 'status', 'dry_run', 'items_imported', 'organizations_created', 'created_at']
    list_filter = ['source_type', 'status', 'dry_run', 'created_at']
    search_fields = ['target_organization__name', 'source_url']
    readonly_fields = ['started_at', 'completed_at', 'items_imported', 'items_skipped', 'items_failed', 'total_items', 'organizations_created', 'organizations_matched', 'import_log', 'error_message']

    fieldsets = [
        ('Source Configuration', {
            'fields': ['source_type', 'source_url', 'source_api_key']
        }),
        ('Import Settings', {
            'fields': ['target_organization', 'use_fuzzy_matching', 'fuzzy_match_threshold', 'import_assets', 'import_passwords', 'import_documents', 'import_contacts', 'import_locations', 'import_networks', 'dry_run']
        }),
        ('Execution', {
            'fields': ['status', 'started_by', 'started_at', 'completed_at']
        }),
        ('Results', {
            'fields': ['organizations_created', 'organizations_matched', 'total_items', 'items_imported', 'items_skipped', 'items_failed', 'error_message']
        }),
        ('Log', {
            'fields': ['import_log'],
            'classes': ['collapse']
        }),
    ]


@admin.register(OrganizationMapping)
class OrganizationMappingAdmin(admin.ModelAdmin):
    """Admin interface for organization mappings."""

    list_display = ['id', 'import_job', 'source_name', 'organization', 'was_created', 'match_score']
    list_filter = ['was_created', 'import_job']
    search_fields = ['source_name', 'organization__name']
    readonly_fields = ['import_job', 'source_id', 'source_name', 'organization', 'was_created', 'match_score']


@admin.register(ImportMapping)
class ImportMappingAdmin(admin.ModelAdmin):
    """Admin interface for import mappings."""

    list_display = ['id', 'import_job', 'source_type', 'source_id', 'target_model', 'target_id', 'target_organization']
    list_filter = ['source_type', 'target_model']
    search_fields = ['source_id', 'target_id']
    readonly_fields = ['import_job', 'source_type', 'source_id', 'source_organization_id', 'target_model', 'target_id', 'target_organization']
