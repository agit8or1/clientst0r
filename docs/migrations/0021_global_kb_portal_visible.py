"""Global KB articles are shown in every customer portal by default: turn the
portal flag on for existing live global articles. Org-scoped rows are never
touched (they include internal documentation)."""
from django.db import migrations


def show_global_in_portals(apps, schema_editor):
    Document = apps.get_model('docs', 'Document')
    Document.objects.filter(is_global=True, is_template=False, is_archived=False,
                            is_client_visible=False).update(is_client_visible=True)


class Migration(migrations.Migration):

    dependencies = [
        ('docs', '0020_agreement_reminder_opt_out'),
    ]

    operations = [
        migrations.RunPython(show_global_in_portals, migrations.RunPython.noop),
    ]
