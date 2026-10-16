"""SchedulerWallboard.token: plaintext -> encrypted (enc2$) + HMAC lookup column.

A wallboard URL is typed or pasted into a TV whenever a screen is set up or
replaced, so the settings page must be able to show it again: it is
encrypted rather than only hashed. The public view looks the board up by
`token_hash`. Existing links keep working.
"""
import vault.secret_fields
from django.db import migrations, models
from vault.secret_fields import hash_and_seal_token_operation


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0004_scheduledtask_alert_before_unit'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedulerwallboard',
            name='token_hash',
            field=models.CharField(editable=False, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='schedulerwallboard',
            name='token',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Random component of the public URL (encrypted at rest). Rotating it breaks every existing link immediately.'),
        ),
        hash_and_seal_token_operation('scheduling', 'SchedulerWallboard', 'token', 'token_hash',
                                      'scheduling.wallboard'),
        migrations.AlterField(
            model_name='schedulerwallboard',
            name='token_hash',
            field=models.CharField(db_index=True, editable=False, help_text='HMAC-SHA256 of the token; the public URL is looked up by it.', max_length=64, unique=True),
        ),
    ]
