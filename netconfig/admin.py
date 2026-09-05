from django.contrib import admin

from .models import ConfigBackup


@admin.register(ConfigBackup)
class ConfigBackupAdmin(admin.ModelAdmin):
    list_display = ('asset', 'captured_at', 'source', 'firmware_version', 'is_approved')
    list_filter = ('source', 'is_approved', 'organization')
    search_fields = ('asset__name', 'firmware_version', 'note')
    # A snapshot is a record of what was true. Editing the body through the
    # admin would quietly destroy the only thing it is for.
    readonly_fields = ('body', 'content_hash', 'captured_at', 'last_seen_at')
