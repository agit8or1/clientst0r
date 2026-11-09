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

    def _record_deletion(self, request, count):
        # Deleting audit entries is itself recorded (v3.17.652).
        AuditLog.log(user=request.user, action='delete', object_type='audit_log',
                     description=f'Deleted {count} audit log entries in Django admin',
                     ip_address=request.META.get('REMOTE_ADDR'),
                     extra_data={'event': 'audit_log_admin_delete', 'deleted': count})

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        self._record_deletion(request, 1)

    def delete_queryset(self, request, queryset):
        count = queryset.count()
        super().delete_queryset(request, queryset)
        self._record_deletion(request, count)
