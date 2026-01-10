"""
Vault admin configuration
"""
from django.contrib import admin
from .models import Password, PasswordRelation


@admin.register(Password)
class PasswordAdmin(admin.ModelAdmin):
    list_display = ['title', 'username', 'organization', 'created_by', 'created_at']
    list_filter = ['organization', 'created_at']
    search_fields = ['title', 'username', 'url']
    readonly_fields = ['created_at', 'updated_at', 'encrypted_password']
    raw_id_fields = ['organization', 'created_by', 'last_modified_by']
    filter_horizontal = ['tags']

    def get_readonly_fields(self, request, obj=None):
        # Never show decrypted password in admin
        return self.readonly_fields


@admin.register(PasswordRelation)
class PasswordRelationAdmin(admin.ModelAdmin):
    list_display = ['password', 'relation_type', 'relation_id', 'created_at']
    list_filter = ['relation_type']
    raw_id_fields = ['password']
