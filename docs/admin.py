"""
Docs admin configuration
"""
from django.contrib import admin
from .models import Document, DocumentVersion


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'organization', 'is_published', 'created_by', 'created_at']
    list_filter = ['is_published', 'organization', 'created_at']
    search_fields = ['title', 'slug', 'body']
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['organization', 'created_by', 'last_modified_by']
    filter_horizontal = ['tags']


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ['document', 'version_number', 'title', 'created_by', 'created_at']
    list_filter = ['created_at']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['document', 'created_by']
