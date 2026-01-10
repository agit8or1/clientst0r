"""
Core admin configuration
"""
from django.contrib import admin
from .models import Organization, Tag


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'color', 'created_at']
    list_filter = ['organization', 'created_at']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}
