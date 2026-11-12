"""Give the shipped staff role templates the new contract-document flags.

New RoleTemplate flags default to off, so without this nobody but superusers
(and MSP staff without a global role, who keep every-customer reach) could
use contract documents after upgrading. Owner and Administrator get all of
them; IT Manager gets view, edit, approve and send. Custom roles are left
alone: their admins opt in in Access Management.
"""
from django.db import migrations

ALL = ['contracts_view', 'contracts_edit', 'contracts_manage_templates', 'contracts_approve', 'contracts_send',
       'contracts_void', 'contracts_view_audit', 'contracts_manage_settings']
MANAGER = ['contracts_view', 'contracts_edit', 'contracts_approve', 'contracts_send']


def grant(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    for name, flags in (('Owner', ALL), ('Administrator', ALL), ('IT Manager', MANAGER)):
        RoleTemplate.objects.filter(is_system_template=True, name=name).update(**{f: True for f in flags})


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0045_roletemplate_contracts_permissions'),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
