from django.contrib import admin

from .models import RMMApproval, RMMPermissionOverride


@admin.register(RMMPermissionOverride)
class RMMPermissionOverrideAdmin(admin.ModelAdmin):
    """Read-only: changes go through Settings → Security → RMM Permissions,
    where widening needs a second administrator."""
    list_display = ('pk', 'effect', 'action', 'organization', 'user', 'role_template', 'status', 'expires_at')
    list_filter = ('effect', 'status')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RMMApproval)
class RMMApprovalAdmin(admin.ModelAdmin):
    list_display = ('pk', 'action', 'requester', 'organization', 'approval_level', 'status', 'decided_by')
    list_filter = ('status', 'approval_level')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
