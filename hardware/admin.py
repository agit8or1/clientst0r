from django.contrib import admin

from .models import (
    Cable, CableTermination, CatalogImportJob, CatalogSource, ComponentTemplate, DevicePort, HardwareDevice,
    HardwareModel, LabelTemplate, LayoutTemplate, Manufacturer, ModelRequest,
)


@admin.register(CatalogSource)
class CatalogSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'revision', 'imported_at', 'license_name')


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    search_fields = ('name',)
    list_display = ('name', 'slug')


class ComponentInline(admin.TabularInline):
    model = ComponentTemplate
    extra = 0
    fields = ('component_class', 'name', 'label', 'type', 'connector', 'poe_mode', 'combo_group', 'origin')


@admin.register(HardwareModel)
class HardwareModelAdmin(admin.ModelAdmin):
    search_fields = ('model', 'part_number', 'manufacturer__name')
    list_display = ('__str__', 'kind', 'category', 'category_source', 'u_height', 'spec_provenance', 'is_generic', 'revision')
    list_filter = ('kind', 'category', 'spec_provenance', 'is_generic', 'locally_modified')
    raw_id_fields = ('manufacturer', 'equipment_model', 'source')
    inlines = [ComponentInline]


@admin.register(LayoutTemplate)
class LayoutTemplateAdmin(admin.ModelAdmin):
    list_display = ('hardware_model', 'version', 'is_current', 'accuracy', 'auto_generated')
    list_filter = ('accuracy', 'is_current', 'auto_generated')
    raw_id_fields = ('hardware_model',)


@admin.register(CatalogImportJob)
class CatalogImportJobAdmin(admin.ModelAdmin):
    list_display = ('pk', 'revision', 'status', 'processed_files', 'total_files', 'started_at')


@admin.register(HardwareDevice)
class HardwareDeviceAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'organization', 'hardware_model', 'status')
    list_filter = ('status', 'organization')
    raw_id_fields = ('asset', 'hardware_model', 'site', 'parent_device', 'parent_bay')


@admin.register(DevicePort)
class DevicePortAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'component_class', 'connector', 'mode', 'untagged_vlan')
    search_fields = ('name', 'description', 'device__asset__name')
    raw_id_fields = ('device', 'module', 'untagged_vlan', 'voice_vlan', 'lag', 'breakout_parent', 'power_port')


class TerminationInline(admin.TabularInline):
    model = CableTermination
    extra = 0
    raw_id_fields = ('port',)


@admin.register(Cable)
class CableAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'organization', 'cable_type', 'status')
    inlines = [TerminationInline]


admin.site.register(LabelTemplate)
admin.site.register(ModelRequest)
