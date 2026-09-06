from django.contrib import admin

from .models import (
    NetworkDiscoveryAssetResult, NetworkDiscoveryImport, NetworkDiscoveryToken,
)


@admin.register(NetworkDiscoveryToken)
class NetworkDiscoveryTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'location', 'state', 'expires_at',
                    'use_count', 'max_uses')
    list_filter = ('organization',)
    # The hash is not an editable field, and there is no plaintext to show.
    readonly_fields = ('token_hash', 'use_count', 'used_at',
                       'source_ip_last_used', 'user_agent_last_used')


@admin.register(NetworkDiscoveryImport)
class NetworkDiscoveryImportAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'location', 'device_count',
                    'imported_count', 'updated_count', 'error_count',
                    'is_dry_run', 'created_at')
    list_filter = ('organization', 'is_dry_run')


@admin.register(NetworkDiscoveryAssetResult)
class NetworkDiscoveryAssetResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'ip_address', 'mac_address', 'hostname', 'status')
    list_filter = ('status', 'organization')
    search_fields = ('ip_address', 'mac_address', 'hostname')
