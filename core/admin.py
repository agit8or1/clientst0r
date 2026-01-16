"""
Core admin configuration
"""
from django.contrib import admin
from django.contrib import messages
from django.db.models import Count
from .models import Organization, Tag


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['created_at', 'updated_at']

    def delete_model(self, request, obj):
        """Override delete to show warning with data counts."""
        # Count related data
        counts = {
            'Assets': obj.assets.count() if hasattr(obj, 'assets') else 0,
            'Passwords': obj.passwords.count() if hasattr(obj, 'passwords') else 0,
            'Documents': obj.documents.count() if hasattr(obj, 'documents') else 0,
            'Contacts': obj.contacts.count() if hasattr(obj, 'contacts') else 0,
            'Processes': obj.processes.count() if hasattr(obj, 'processes') else 0,
            'Locations': obj.locations.count() if hasattr(obj, 'locations') else 0,
            'Integrations': (
                obj.psa_connections.count() + obj.rmm_connections.count()
                if hasattr(obj, 'psa_connections') and hasattr(obj, 'rmm_connections')
                else 0
            ),
        }

        # Show warning message
        total = sum(counts.values())
        if total > 0:
            detail = ', '.join([f"{k}: {v}" for k, v in counts.items() if v > 0])
            messages.warning(
                request,
                f"Deleting organization '{obj.name}' will cascade delete {total} related records: {detail}. "
                f"Audit logs will be preserved."
            )

        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Override bulk delete to show warning."""
        total_orgs = queryset.count()
        messages.warning(
            request,
            f"Deleting {total_orgs} organizations will cascade delete all their related data. "
            f"Audit logs will be preserved. This action cannot be undone."
        )
        super().delete_queryset(request, queryset)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'color', 'created_at']
    list_filter = ['organization', 'created_at']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}
