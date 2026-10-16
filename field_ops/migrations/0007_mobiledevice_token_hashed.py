"""MobileDevice.token: authtoken.Token -> api_mobile.MobileAuthToken.

The old foreign key column held the DRF token's primary key, which *is* the
raw token. A new column is added, filled by hashing the old value (so a
device keeps pointing at the same sign-in), and the old column dropped.
"""
import django.db.models.deletion
from django.db import migrations, models


def repoint(apps, schema_editor):
    from vault.secret_fields import hash_token
    MobileDevice = apps.get_model('field_ops', 'MobileDevice')
    MobileAuthToken = apps.get_model('api_mobile', 'MobileAuthToken')
    for dev_pk, raw in MobileDevice.objects.exclude(token__isnull=True).values_list('pk', 'token_id'):
        row = MobileAuthToken.objects.filter(key_hash=hash_token(raw, 'api_mobile.token')).first()
        MobileDevice.objects.filter(pk=dev_pk).update(auth_token=row)


class Migration(migrations.Migration):

    dependencies = [
        ('api_mobile', '0001_initial'),
        ('field_ops', '0006_mobiledevice_expo_push'),
    ]

    operations = [
        migrations.AddField(
            model_name='mobiledevice',
            name='auth_token',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='api_mobile.mobileauthtoken'),
        ),
        migrations.RunPython(repoint, migrations.RunPython.noop, elidable=False),
        migrations.RemoveField(
            model_name='mobiledevice',
            name='token',
        ),
        migrations.RenameField(
            model_name='mobiledevice',
            old_name='auth_token',
            new_name='token',
        ),
    ]
