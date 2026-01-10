"""
Integrations admin configuration
"""
from django.contrib import admin
from .models import PSAConnection, PSACompany, PSAContact, PSATicket, ExternalObjectMap


@admin.register(PSAConnection)
class PSAConnectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'provider_type', 'organization', 'is_active', 'sync_enabled', 'last_sync_at', 'last_sync_status']
    list_filter = ['provider_type', 'is_active', 'sync_enabled', 'last_sync_status']
    search_fields = ['name', 'base_url']
    readonly_fields = ['created_at', 'updated_at', 'last_sync_at', 'last_sync_status', 'last_error']
    raw_id_fields = ['organization']


@admin.register(PSACompany)
class PSACompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'connection', 'external_id', 'phone', 'last_synced_at']
    list_filter = ['connection', 'organization']
    search_fields = ['name', 'external_id', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at', 'raw_data']
    raw_id_fields = ['organization', 'connection']


@admin.register(PSAContact)
class PSAContactAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'company', 'connection', 'last_synced_at']
    list_filter = ['connection', 'organization']
    search_fields = ['first_name', 'last_name', 'email', 'external_id']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at', 'raw_data']
    raw_id_fields = ['organization', 'connection', 'company']


@admin.register(PSATicket)
class PSATicketAdmin(admin.ModelAdmin):
    list_display = ['ticket_number', 'subject', 'status', 'priority', 'company', 'connection', 'external_updated_at']
    list_filter = ['status', 'priority', 'connection', 'organization']
    search_fields = ['ticket_number', 'subject', 'external_id']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at', 'external_created_at', 'external_updated_at', 'raw_data']
    raw_id_fields = ['organization', 'connection', 'company', 'contact']


@admin.register(ExternalObjectMap)
class ExternalObjectMapAdmin(admin.ModelAdmin):
    list_display = ['connection', 'external_type', 'external_id', 'local_type', 'local_id', 'last_synced_at']
    list_filter = ['external_type', 'local_type', 'connection']
    search_fields = ['external_id']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at']
    raw_id_fields = ['organization', 'connection']
