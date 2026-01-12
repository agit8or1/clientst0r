"""
Assets admin configuration
"""
from django.contrib import admin
from .models import Contact, Asset, Relationship, Vendor, EquipmentModel, NetworkPortConfiguration


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


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ['name', 'website', 'support_phone', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'website', 'description']
    prepopulated_fields = {'slug': ('name',)}
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'is_active')
        }),
        ('Contact Information', {
            'fields': ('website', 'support_url', 'support_phone')
        }),
        ('Additional Data', {
            'fields': ('custom_fields',),
            'classes': ('collapse',)
        }),
    )


@admin.register(EquipmentModel)
class EquipmentModelAdmin(admin.ModelAdmin):
    list_display = ['model_name', 'vendor', 'equipment_type', 'is_rackmount', 'rack_units', 'is_active']
    list_filter = ['vendor', 'equipment_type', 'is_rackmount', 'is_active']
    search_fields = ['model_name', 'model_number', 'vendor__name', 'description']
    prepopulated_fields = {'slug': ('model_name',)}
    raw_id_fields = ['vendor']
    fieldsets = (
        ('Basic Information', {
            'fields': ('vendor', 'model_name', 'model_number', 'slug', 'equipment_type', 'description', 'is_active')
        }),
        ('Physical Specifications', {
            'fields': ('is_rackmount', 'rack_units', 'specifications')
        }),
        ('Documentation', {
            'fields': ('datasheet_url', 'documentation_url')
        }),
        ('Lifecycle', {
            'fields': ('release_date', 'eol_date', 'eos_date')
        }),
        ('Additional Data', {
            'fields': ('custom_fields',),
            'classes': ('collapse',)
        }),
    )


@admin.register(NetworkPortConfiguration)
class NetworkPortConfigurationAdmin(admin.ModelAdmin):
    list_display = ['configuration_name', 'equipment_model', 'asset', 'organization', 'is_template', 'get_port_count']
    list_filter = ['is_template', 'equipment_model__equipment_type', 'organization']
    search_fields = ['configuration_name', 'equipment_model__model_name', 'asset__name', 'notes']
    raw_id_fields = ['organization', 'equipment_model', 'asset']
    fieldsets = (
        ('Basic Information', {
            'fields': ('organization', 'equipment_model', 'asset', 'configuration_name', 'is_template')
        }),
        ('Configuration', {
            'fields': ('ports', 'vlans', 'notes')
        }),
    )

    def get_port_count(self, obj):
        return obj.get_port_count()
    get_port_count.short_description = 'Ports'
