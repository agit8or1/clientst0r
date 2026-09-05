from django.contrib import admin

from .models import StatusPage, StatusPageService


class StatusPageServiceInline(admin.TabularInline):
    model = StatusPageService
    extra = 0


@admin.register(StatusPage)
class StatusPageAdmin(admin.ModelAdmin):
    list_display = ('display_title', 'organization', 'is_enabled', 'updated_at')
    list_filter = ('is_enabled', 'organization')
    search_fields = ('title',)
    # The token acts as a credential; it is not something to edit by hand.
    readonly_fields = ('token',)
    inlines = [StatusPageServiceInline]
