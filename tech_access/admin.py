"""Django admin: a protected account's e-mail address moves only through a
protected change (tech_access.services.propose_email_change), the same as
from the user edit page."""
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

User = get_user_model()


class ProtectedEmailUserAdmin(UserAdmin):
    def save_model(self, request, obj, form, change):
        if change and 'email' in form.changed_data:
            from .services import email_is_protected, propose_email_change
            before = User.objects.get(pk=obj.pk)
            if email_is_protected(before) or obj.is_superuser:
                new_email = obj.email
                obj.email = before.email
                try:
                    propose_email_change(before, new_email, request.user, request=request)
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.warning(request, 'The e-mail address was not changed yet. Confirm the change under '
                                              'Settings → Security → Technician Access; a second administrator '
                                              'then approves it.')
        super().save_model(request, obj, form, change)


if admin.site.is_registered(User):
    admin.site.unregister(User)
admin.site.register(User, ProtectedEmailUserAdmin)
