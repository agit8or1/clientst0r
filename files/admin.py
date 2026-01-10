"""
Files admin configuration
"""
from django.contrib import admin
from .models import Attachment


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['original_filename', 'entity_type', 'entity_id', 'organization', 'uploaded_by', 'created_at']
    list_filter = ['entity_type', 'organization', 'created_at']
    search_fields = ['original_filename', 'description']
    readonly_fields = ['created_at', 'updated_at', 'file_size']
    raw_id_fields = ['organization', 'uploaded_by']
