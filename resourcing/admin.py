from django.contrib import admin

from .models import (
    BillableTarget, Holiday, LeaveRequest, TechCostRate,
    ShiftAssignment, ShiftTemplate, UserSkill, UserCertification, WorkingHours,
)


@admin.register(UserSkill)
class UserSkillAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'proficiency', 'years_experience', 'updated_at')
    list_filter = ('proficiency',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'name')
    autocomplete_fields = ('user',)
    list_editable = ('proficiency',)
    ordering = ('user', 'name')


@admin.register(UserCertification)
class UserCertificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'issuer', 'issued_at', 'expires_at', 'is_expired')
    list_filter = ('issuer',)
    search_fields = (
        'user__username', 'user__first_name', 'user__last_name',
        'name', 'issuer', 'credential_id',
    )
    autocomplete_fields = ('user',)
    date_hierarchy = 'issued_at'
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(boolean=True, description='Expired?')
    def is_expired(self, obj):
        return obj.is_expired


@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ('user', 'weekday', 'start_time', 'end_time', 'is_active')
    list_filter = ('weekday', 'is_active')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    autocomplete_fields = ('user',)
    list_editable = ('is_active',)


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'organization', 'is_recurring_yearly', 'updated_at')
    list_filter = ('is_recurring_yearly', 'organization')
    search_fields = ('name', 'notes')
    autocomplete_fields = ('organization',)
    date_hierarchy = 'date'
    ordering = ('date',)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'leave_type', 'start_date', 'end_date',
                    'status', 'approver', 'decided_at')
    list_filter = ('status', 'leave_type')
    search_fields = (
        'user__username', 'user__first_name', 'user__last_name',
        'notes', 'decision_note',
    )
    autocomplete_fields = ('user', 'approver')
    date_hierarchy = 'start_date'
    readonly_fields = ('created_at', 'updated_at', 'decided_at')


@admin.register(BillableTarget)
class BillableTargetAdmin(admin.ModelAdmin):
    list_display = ('user', 'target_hours_per_week', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    autocomplete_fields = ('user',)
    list_editable = ('target_hours_per_week', 'is_active')


@admin.register(TechCostRate)
class TechCostRateAdmin(admin.ModelAdmin):
    list_display = ('user', 'rate_per_hour', 'effective_from', 'updated_at')
    list_filter = ('effective_from',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'notes')
    autocomplete_fields = ('user',)
    date_hierarchy = 'effective_from'
    ordering = ('-effective_from', 'user__username')


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time', 'is_on_call', 'is_active')
    list_filter = ('is_on_call', 'is_active')


@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ('template', 'user', 'team', 'weekdays', 'effective_from', 'effective_until')
    list_filter = ('template',)
