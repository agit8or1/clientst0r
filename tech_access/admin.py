"""Django admin: a protected account's e-mail address moves only through a
protected change (tech_access.services.propose_email_change), the same as
from the user edit page — and, with the superuser-grant policy on, so does
granting superuser (tech_access.services.propose_superuser_grant)."""
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
        grant_wanted = False
        if obj.is_superuser and 'is_superuser' in form.changed_data:
            from .services import superuser_policy_on
            was = change and User.objects.filter(pk=obj.pk, is_superuser=True).exists()
            if not was and superuser_policy_on():
                # Saved without superuser; a second administrator approves it.
                obj.is_superuser = False
                grant_wanted = True
        super().save_model(request, obj, form, change)
        if grant_wanted:
            from .services import propose_superuser_grant
            try:
                propose_superuser_grant(obj, request.user, request=request)
            except ValueError as exc:
                messages.error(request, f'Superuser was not granted: {exc}')
            else:
                messages.warning(request, 'Superuser was not granted yet. Confirm the request under Admin → '
                                          'Security → Superuser Approval; a different administrator then '
                                          'approves it.')


if admin.site.is_registered(User):
    admin.site.unregister(User)
admin.site.register(User, ProtectedEmailUserAdmin)
