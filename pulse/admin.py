from django.contrib import admin

from .models import PulseCheck, PulseOptOut, PulseQuestion, PulseResponse, PulseSend


class PulseQuestionInline(admin.TabularInline):
    model = PulseQuestion
    extra = 0


@admin.register(PulseCheck)
class PulseCheckAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'schedule', 'audience', 'all_organizations', 'updated_at')
    list_filter = ('is_active', 'schedule', 'audience')
    search_fields = ('name',)
    filter_horizontal = ('organizations', 'audience_role_templates', 'specific_users', 'specific_contacts')
    inlines = [PulseQuestionInline]
    readonly_fields = ('created_by', 'created_at', 'updated_at')


@admin.register(PulseSend)
class PulseSendAdmin(admin.ModelAdmin):
    list_display = ('pulse_check', 'trigger', 'period_key', 'created_at', 'expires_at',
                    'recipient_count', 'emailed_count')
    list_filter = ('trigger',)
    readonly_fields = ('questions', 'created_at', 'sent_by')


@admin.register(PulseResponse)
class PulseResponseAdmin(admin.ModelAdmin):
    list_display = ('email', 'organization', 'send', 'email_status', 'responded_at')
    list_filter = ('email_status', 'organization')
    search_fields = ('email', 'name')
    # The token hash is never useful to show; answers are the respondent's.
    exclude = ('token_hash',)
    readonly_fields = ('send', 'organization', 'user', 'contact', 'email', 'answers',
                       'responded_at', 'responded_via', 'responded_ip', 'created_at')


@admin.register(PulseOptOut)
class PulseOptOutAdmin(admin.ModelAdmin):
    list_display = ('email', 'via', 'created_at')
    search_fields = ('email',)
