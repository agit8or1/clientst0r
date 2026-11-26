"""First-install Setup Assistant state (Phase 96.2, core/setup_assistant.py).

How "fresh install" is decided, so an upgraded install is never redirected:

* AddField with default 'not_offered': every settings row that already
  exists (any install that was ever opened in a browser) gets 'not_offered'.
* AlterField to default 'offered': only rows created from now on start
  'offered'. On a fresh install the row does not exist while migrations run
  (install.sh and the Docker entrypoint migrate before any page is served),
  so SystemSetting.get_settings() creates it later with 'offered'.
* RunPython: an install that has user accounts but no settings row yet is
  an upgrade too; its row is created here as 'not_offered'. A database with
  a row but no users at all (a fresh database where something created the
  row early) is set to 'offered'.

The runtime guard in core.setup_assistant.looks_fresh() is the second line:
a restored backup or a database created some other way fails it and drops
to 'not_offered' for good. Reverse: the fields are removed; the data step is
a no-op.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def mark_install(apps, schema_editor):
    alias = schema_editor.connection.alias
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    SystemSetting = apps.get_model('core', 'SystemSetting')
    has_users = User.objects.using(alias).exists()
    row = SystemSetting.objects.using(alias).filter(pk=1).first()
    if has_users:
        if row is None:
            SystemSetting.objects.using(alias).create(pk=1, setup_assistant_state='not_offered')
        else:
            SystemSetting.objects.using(alias).filter(pk=1).update(setup_assistant_state='not_offered')
    elif row is not None:
        SystemSetting.objects.using(alias).filter(pk=1).update(setup_assistant_state='offered')


STATES = [
    ('not_offered', 'Not offered automatically'),
    ('offered', 'Offered (new install)'),
    ('in_progress', 'In progress'),
    ('completed', 'Completed'),
    ('dismissed', 'Dismissed ("Later")'),
]
HELP = ('First-install Setup Assistant. Only "offered" and "in progress" are offered '
        'automatically after sign-in.')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0125_module_switches_on_by_default'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsetting',
            name='setup_assistant_state',
            field=models.CharField(choices=STATES, default='not_offered', help_text=HELP, max_length=12),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='setup_assistant_state',
            field=models.CharField(choices=STATES, default='offered', help_text=HELP, max_length=12),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='setup_assistant_completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='setup_assistant_completed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(mark_install, migrations.RunPython.noop),
    ]
