from django.conf import settings
from django.db import migrations


def keep_existing_installs_on_main(apps, schema_editor):
    """Installs that existed before channels followed main. Keep them there
    (Preview) so an upgrade doesn't silently stop offering updates; a fresh
    install (no users yet) keeps the Stable default. Admins switch on
    Settings → Updates."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    if not User.objects.exists():
        return
    SystemSetting = apps.get_model('core', 'SystemSetting')
    SystemSetting.objects.update(update_channel='preview')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0082_systemsetting_update_channel'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(keep_existing_installs_on_main, migrations.RunPython.noop),
    ]
