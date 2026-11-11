"""Keep existing access when `monitoring_view` and `integrations_view` start
being enforced.

Until this release both flags were stored and shown in the role editor as
"not enforced yet": every signed-in user with a role could open /monitoring/
and /integrations/ whatever the flag said. SectionPermissionMiddleware now
checks them, so a role saved with either flag off (the Editor, Help Desk,
Documentation Writer, Read-Only, Technician, Client and Client Admin
templates ship with `integrations_view` off, and several with
`monitoring_view` off) would lose pages its users open today.

This migration switches both flags on for every existing role template, so
nobody loses access on upgrade. Admins who want to restrict a role untick
the flag in Access Management afterwards; from now on it takes effect.

`files_view` is not touched: attachment downloads have checked it since
v3.17.600, so a role with it off already had no file access.

Not reversible in a meaningful way (the previous values carried no effect),
so the reverse is a no-op.
"""
from django.db import migrations


def enable_flags(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    RoleTemplate.objects.filter(monitoring_view=False).update(monitoring_view=True)
    RoleTemplate.objects.filter(integrations_view=False).update(integrations_view=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0039_roletemplate_routing_manage_rules_and_more'),
    ]

    operations = [
        migrations.RunPython(enable_flags, migrations.RunPython.noop),
    ]
