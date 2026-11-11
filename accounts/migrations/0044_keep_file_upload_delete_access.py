"""Keep existing access when `files_upload` and `files_delete` start being
enforced.

Until this release /files/upload/ and /files/delete/<id>/ (asset, rack and
vehicle photos) checked neither flag: anyone who could open /files/ - which
since the release before this one means holding `files_view` - could upload
and delete attachments of the selected customer. Both views now require the
flag for that customer, so a role saved with either flag off would lose
something its users can do today.

As accounts 0040 did for monitoring_view / integrations_view, this switches
both flags on for every role template that has `files_view`. Admins who want
a role to stop uploading or deleting untick the flag in Access Management;
from now on that takes effect. Roles without `files_view` could not reach
/files/ at all, so they are left alone.

Memberships without a role template use the built-in Owner / Admin / Editor
/ Read-Only flags from code, which this migration cannot change: Editor keeps
upload but loses delete, Read-Only loses both.

Not reversible in a meaningful way (the previous values carried no effect),
so the reverse is a no-op.
"""
from django.db import migrations


def enable_flags(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    RoleTemplate.objects.filter(files_view=True, files_upload=False).update(files_upload=True)
    RoleTemplate.objects.filter(files_view=True, files_delete=False).update(files_delete=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0043_userprofile_ldap_groups_checked_at'),
    ]

    operations = [
        migrations.RunPython(enable_flags, migrations.RunPython.noop),
    ]
