"""
Integrations admin configuration
"""
from django.contrib import admin
from .models import (
    PSAConnection, PSACompany, PSAContact, PSATicket, ExternalObjectMap,
    RMMConnection, RMMDevice, RMMAlert, RMMSoftware
)


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


# ============================================================================
# RMM Admin Classes
# ============================================================================

@admin.register(RMMConnection)
class RMMConnectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'provider_type', 'organization', 'is_active', 'sync_enabled', 'last_sync_at', 'last_sync_status']
    list_filter = ['provider_type', 'is_active', 'sync_enabled', 'last_sync_status']
    search_fields = ['name', 'base_url']
    readonly_fields = ['created_at', 'updated_at', 'last_sync_at', 'last_sync_status', 'last_error']
    raw_id_fields = ['organization']
    fieldsets = (
        ('Basic Information', {
            'fields': ('organization', 'provider_type', 'name', 'base_url')
        }),
        ('Sync Settings', {
            'fields': ('sync_enabled', 'sync_devices', 'sync_alerts', 'sync_software',
                      'sync_network_config', 'sync_interval_minutes', 'map_to_assets')
        }),
        ('Status', {
            'fields': ('is_active', 'last_sync_at', 'last_sync_status', 'last_error')
        }),
        ('Advanced', {
            'fields': ('field_mappings',),
            'classes': ('collapse',)
        }),
    )


@admin.register(RMMDevice)
class RMMDeviceAdmin(admin.ModelAdmin):
    list_display = ['device_name', 'device_type', 'is_online', 'connection', 'linked_asset', 'last_seen']
    list_filter = ['device_type', 'is_online', 'os_type', 'connection', 'organization']
    search_fields = ['device_name', 'hostname', 'serial_number', 'ip_address', 'external_id']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at', 'raw_data']
    raw_id_fields = ['organization', 'connection', 'linked_asset']
    fieldsets = (
        ('Identification', {
            'fields': ('organization', 'connection', 'external_id', 'device_name', 'device_type')
        }),
        ('Hardware', {
            'fields': ('manufacturer', 'model', 'serial_number')
        }),
        ('Operating System', {
            'fields': ('os_type', 'os_version')
        }),
        ('Network', {
            'fields': ('hostname', 'ip_address', 'mac_address')
        }),
        ('Status', {
            'fields': ('is_online', 'last_seen')
        }),
        ('Asset Mapping', {
            'fields': ('linked_asset',)
        }),
        ('Sync Data', {
            'fields': ('last_synced_at', 'raw_data'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RMMAlert)
class RMMAlertAdmin(admin.ModelAdmin):
    list_display = ['alert_type', 'severity', 'status', 'device', 'connection', 'triggered_at']
    list_filter = ['severity', 'status', 'connection', 'organization']
    search_fields = ['alert_type', 'message', 'external_id']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at', 'raw_data']
    raw_id_fields = ['organization', 'connection', 'device']
    date_hierarchy = 'triggered_at'
    fieldsets = (
        ('Alert Information', {
            'fields': ('organization', 'connection', 'device', 'external_id',
                      'alert_type', 'message')
        }),
        ('Severity & Status', {
            'fields': ('severity', 'status')
        }),
        ('Timestamps', {
            'fields': ('triggered_at', 'resolved_at')
        }),
        ('Sync Data', {
            'fields': ('last_synced_at', 'raw_data'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RMMSoftware)
class RMMSoftwareAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'vendor', 'device', 'connection', 'install_date']
    list_filter = ['connection', 'organization', 'vendor']
    search_fields = ['name', 'version', 'vendor', 'external_id']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_at', 'raw_data']
    raw_id_fields = ['organization', 'connection', 'device']
    fieldsets = (
        ('Software Information', {
            'fields': ('organization', 'connection', 'device', 'external_id',
                      'name', 'version', 'vendor')
        }),
        ('Installation', {
            'fields': ('install_date',)
        }),
        ('Sync Data', {
            'fields': ('last_synced_at', 'raw_data'),
            'classes': ('collapse',)
        }),
    )
