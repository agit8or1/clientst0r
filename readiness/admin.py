from django.contrib import admin

from .models import DocumentationStandard, StandardException, StandardRequirement


class StandardRequirementInline(admin.TabularInline):
    model = StandardRequirement
    extra = 0


@admin.register(DocumentationStandard)
class DocumentationStandardAdmin(admin.ModelAdmin):
    list_display = ('name', 'scope', 'scope_value', 'is_active', 'version', 'updated_at')
    list_filter = ('scope', 'is_active')
    inlines = [StandardRequirementInline]


@admin.register(StandardException)
class StandardExceptionAdmin(admin.ModelAdmin):
    list_display = ('organization', 'standard', 'requirement', 'expires_at', 'created_by', 'created_at')
    list_filter = ('standard',)
    raw_id_fields = ('organization', 'requirement')
