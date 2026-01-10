"""
API admin configuration
"""
from django.contrib import admin
from .models import APIKey


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'key_prefix', 'organization', 'user', 'role', 'is_active', 'last_used_at']
    list_filter = ['role', 'is_active', 'organization']
    search_fields = ['name', 'key_prefix', 'user__username']
    readonly_fields = ['key_hash', 'key_prefix', 'created_at', 'updated_at', 'last_used_at', 'last_used_ip']
    raw_id_fields = ['organization', 'user']
