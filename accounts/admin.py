"""
Accounts admin configuration
"""
from django.contrib import admin
from .models import Membership


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'role', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'organization']
    search_fields = ['user__username', 'user__email', 'organization__name']
    readonly_fields = ['created_at', 'updated_at', 'invited_at']
    raw_id_fields = ['user', 'organization', 'invited_by']
