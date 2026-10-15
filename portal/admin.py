from django.contrib import admin

from .models import PortalAnnouncement


@admin.register(PortalAnnouncement)
class PortalAnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'severity', 'is_active',
                    'is_dismissable', 'expires_at', 'created_at')
    list_filter = ('severity', 'is_active', 'is_dismissable', 'organization')
    search_fields = ('title', 'body', 'organization__name')
    raw_id_fields = ('organization', 'created_by')
    readonly_fields = ('created_at', 'updated_at')


from .models import PortalStatusPhrase  # noqa: E402


@admin.register(PortalStatusPhrase)
class PortalStatusPhraseAdmin(admin.ModelAdmin):
    list_display = ('status', 'phrase', 'updated_at')
    list_filter = ('phrase',)
