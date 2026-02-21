"""
Admin configuration for monitoring app
"""
from django.contrib import admin
from .models import WebsiteMonitor, Expiration, Rack, RackDevice, RackConnection, RackResource, Subnet, IPAddress


@admin.register(WebsiteMonitor)
class WebsiteMonitorAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'status', 'last_checked_at', 'ssl_expires_at', 'organization')
    list_filter = ('status', 'organization', 'is_enabled')
    search_fields = ('name', 'url')
    readonly_fields = ('last_checked_at', 'last_status_code', 'last_response_time_ms', 'ssl_expires_at')


@admin.register(Expiration)
class ExpirationAdmin(admin.ModelAdmin):
    list_display = ('name', 'expiration_type', 'expires_at', 'days_until_expiration', 'organization')
    list_filter = ('expiration_type', 'organization')
    search_fields = ('name', 'notes')
    readonly_fields = ('days_until_expiration', 'is_expired', 'is_expiring_soon')


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ('name', 'rack_type', 'location', 'units', 'available_units', 'power_utilization_percent', 'organization')
    list_filter = ('rack_type', 'organization')
    search_fields = ('name', 'location', 'datacenter', 'building', 'room')
    fieldsets = (
        ('Basic Information', {
            'fields': ('organization', 'name', 'rack_type', 'notes')
        }),
        ('Location', {
            'fields': ('datacenter', 'building', 'floor', 'room', 'aisle', 'location')
        }),
        ('Physical Specifications', {
            'fields': ('units', 'width_inches', 'depth_inches')
        }),
        ('Power & Cooling', {
            'fields': ('power_capacity_watts', 'power_allocated_watts', 'pdu_count',
                      'cooling_capacity_btu', 'ambient_temp_f')
        }),
        ('Network Closet', {
            'fields': ('patch_panel_count', 'total_port_count', 'closet_diagram'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RackDevice)
class RackDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'rack', 'start_unit', 'units', 'power_draw_watts', 'asset')
    list_filter = ('rack__organization', 'rack')
    search_fields = ('name', 'notes')  # Needed for autocomplete in RackConnection


@admin.register(RackConnection)
class RackConnectionAdmin(admin.ModelAdmin):
    list_display = ('from_device', 'to_device', 'connection_type', 'from_port', 'to_port', 'speed')
    list_filter = ('connection_type',)
    search_fields = ('from_device__name', 'to_device__name', 'from_port', 'to_port')
    autocomplete_fields = ('from_device', 'to_device')


@admin.register(RackResource)
class RackResourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'resource_type', 'rack', 'manufacturer', 'model', 'port_count', 'ip_address')
    list_filter = ('resource_type', 'rack__organization', 'rack')
    search_fields = ('name', 'manufacturer', 'model', 'serial_number', 'ip_address')
    fieldsets = (
        ('Basic Information', {
            'fields': ('rack', 'name', 'resource_type', 'notes')
        }),
        ('Hardware Details', {
            'fields': ('manufacturer', 'model', 'serial_number', 'photo')
        }),
        ('Network Specifications', {
            'fields': ('port_count', 'port_speed', 'ip_address', 'mac_address', 'management_url'),
            'classes': ('collapse',)
        }),
        ('Power Specifications', {
            'fields': ('power_draw_watts', 'input_voltage', 'battery_runtime_minutes', 'capacity_va'),
            'classes': ('collapse',)
        }),
        ('Rack Mounting', {
            'fields': ('rack_position',),
            'classes': ('collapse',)
        }),
        ('Warranty & Support', {
            'fields': ('purchase_date', 'warranty_expires', 'support_contract'),
            'classes': ('collapse',)
        }),
        ('Asset Link', {
            'fields': ('asset',),
            'classes': ('collapse',)
        }),
    )


@admin.register(Subnet)
class SubnetAdmin(admin.ModelAdmin):
    list_display = ('name', 'network', 'vlan_id', 'gateway', 'location', 'organization')
    list_filter = ('organization',)
    search_fields = ('name', 'network', 'location')


@admin.register(IPAddress)
class IPAddressAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'hostname', 'status', 'subnet', 'mac_address', 'asset')
    list_filter = ('status', 'subnet__organization', 'subnet')
    search_fields = ('ip_address', 'hostname', 'mac_address', 'description')
