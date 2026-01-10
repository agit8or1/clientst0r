"""
Audit admin configuration
"""
from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'username', 'action', 'object_type', 'object_repr', 'organization', 'success']
    list_filter = ['action', 'success', 'organization', 'timestamp']
    search_fields = ['username', 'object_type', 'object_repr', 'description', 'ip_address']
    readonly_fields = ['timestamp', 'user', 'username', 'action', 'object_type', 'object_id',
                       'object_repr', 'description', 'organization', 'ip_address', 'user_agent',
                       'path', 'extra_data', 'success']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Only superusers can delete audit logs
        return request.user.is_superuser
