from django.contrib import admin
from django.utils import timezone

from .models import MobileAuthToken

# DRF's authtoken admin would let staff mint raw, unhashed tokens that
# nothing authenticates against any more. The app stays installed only
# because historical migrations reference it.
try:
    from rest_framework.authtoken.models import Token, TokenProxy
    for _m in (Token, TokenProxy):
        if admin.site.is_registered(_m):
            admin.site.unregister(_m)
except Exception:
    pass


@admin.register(MobileAuthToken)
class MobileAuthTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_label', 'key_prefix', 'created_at',
                    'last_used_at', 'expires_at', 'revoked_at')
    list_filter = ('revoked_at',)
    search_fields = ('user__username', 'device_label', 'key_prefix')
    readonly_fields = ('user', 'key_hash', 'key_prefix', 'device_label', 'created_at',
                       'last_used_at', 'expires_at', 'revoked_at')
    actions = ['revoke_selected']

    def has_add_permission(self, request):
        # Tokens are issued by signing in on the app, never typed in here.
        return False

    @admin.action(description='Revoke selected mobile sessions')
    def revoke_selected(self, request, queryset):
        n = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f'Revoked {n} mobile session(s).')
