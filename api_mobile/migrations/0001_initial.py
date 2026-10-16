"""Hashed per-device mobile API tokens (v3.17.611).

Creates MobileAuthToken and copies every DRF authtoken.Token into it as an
HMAC (vault.secret_fields.hash_token, purpose 'api_mobile.token'), so apps
already signed in keep working: they keep sending the same key, which now
hashes to a stored row. The raw authtoken rows are deleted afterwards by
0002 (after field_ops 0007 has re-pointed MobileDevice.token).

Reverse drops the new table; the raw tokens are gone by then, so rolling
back past 0002 means users sign in again on their phones.
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

HASH_PURPOSE = 'api_mobile.token'
LEGACY_LABEL = 'Mobile app (signed in before v3.17.611)'


def copy_authtokens(apps, schema_editor):
    from vault.secret_fields import hash_token
    try:
        Token = apps.get_model('authtoken', 'Token')
    except LookupError:
        return
    MobileAuthToken = apps.get_model('api_mobile', 'MobileAuthToken')
    rows = []
    for key, user_id, created in Token.objects.values_list('key', 'user_id', 'created'):
        if not key:
            continue
        key_hash = hash_token(key, HASH_PURPOSE)
        if MobileAuthToken.objects.filter(key_hash=key_hash).exists():
            continue
        rows.append(MobileAuthToken(
            user_id=user_id, key_hash=key_hash, key_prefix=key[:8],
            device_label=LEGACY_LABEL,
            created_at=created or django.utils.timezone.now(),
        ))
    MobileAuthToken.objects.bulk_create(rows)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('authtoken', '0004_alter_tokenproxy_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='MobileAuthToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key_hash', models.CharField(db_index=True, help_text='HMAC-SHA256 of the token. The token itself is returned to the app once and never stored.', max_length=64, unique=True)),
                ('key_prefix', models.CharField(blank=True, help_text='First characters of the token, for identification only.', max_length=12)),
                ('device_label', models.CharField(blank=True, help_text='What signed in, e.g. the app/platform reported at login.', max_length=120)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('expires_at', models.DateTimeField(blank=True, help_text='Optional hard expiry. Empty = valid until revoked.', null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mobile_auth_tokens', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'api_mobile_auth_tokens',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['user', '-created_at'], name='api_mobile__user_id_18a6b0_idx')],
            },
        ),
        migrations.RunPython(copy_authtokens, migrations.RunPython.noop, elidable=False),
    ]
