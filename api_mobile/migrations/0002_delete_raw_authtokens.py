"""Delete the raw DRF authtoken rows once they exist as hashes (0001).

Nothing authenticates against authtoken.Token any more
(api_mobile.authentication.MobileTokenAuthentication reads MobileAuthToken).
Irreversible: the reverse is a no-op.
"""
from django.db import migrations


def delete_raw(apps, schema_editor):
    try:
        Token = apps.get_model('authtoken', 'Token')
    except LookupError:
        return
    Token.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('api_mobile', '0001_initial'),
        # MobileDevice.token must stop referencing authtoken rows first.
        ('field_ops', '0007_mobiledevice_token_hashed'),
    ]

    operations = [
        migrations.RunPython(delete_raw, migrations.RunPython.noop, elidable=False),
    ]
