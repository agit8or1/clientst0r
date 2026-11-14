"""v3.17.678: every existing profile moves to Professional Dark once, at the
product owner's request, so the redesign is what everyone sees after the
update. Users can pick another theme afterwards (profile → Theme, or the
theme toggle in the account menu); this runs only once. Backgrounds are
not touched: a system background policy still applies as configured."""
from django.db import migrations


def forwards(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    UserProfile.objects.exclude(theme='professional').update(theme='professional')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0048_ui_density_dashboard_prefs'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
