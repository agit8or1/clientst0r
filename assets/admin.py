"""
Assets admin configuration
"""
from django.contrib import admin
from .models import Contact, Asset, Relationship


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'phone', 'title', 'organization']
    list_filter = ['organization']
    search_fields = ['first_name', 'last_name', 'email']
    raw_id_fields = ['organization']


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ['name', 'asset_type', 'asset_tag', 'manufacturer', 'model', 'organization']
    list_filter = ['asset_type', 'organization']
    search_fields = ['name', 'asset_tag', 'serial_number', 'manufacturer', 'model']
    raw_id_fields = ['organization', 'primary_contact', 'created_by']
    filter_horizontal = ['tags']


@admin.register(Relationship)
class RelationshipAdmin(admin.ModelAdmin):
    list_display = ['source_type', 'source_id', 'relation_type', 'target_type', 'target_id', 'organization']
    list_filter = ['relation_type', 'source_type', 'target_type']
    raw_id_fields = ['organization']
