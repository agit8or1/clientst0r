"""StatusPage.token: plaintext -> encrypted (enc2$) + HMAC lookup column.

The link stays re-displayable on the page's settings screen (operators share
it whenever a client asks), so it is encrypted rather than only hashed; the
public view looks pages up by `token_hash`. Existing links keep working.
"""
import vault.secret_fields
from django.db import migrations, models
from vault.secret_fields import hash_and_seal_token_operation


class Migration(migrations.Migration):

    dependencies = [
        ('statuspage', '0004_statuspage_visibility_alter_statuspage_is_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='statuspage',
            name='token_hash',
            field=models.CharField(editable=False, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='statuspage',
            name='token',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Random component of the public URL (encrypted at rest). Rotating it breaks every existing link immediately.'),
        ),
        hash_and_seal_token_operation('statuspage', 'StatusPage', 'token', 'token_hash',
                                      'statuspage.link'),
        migrations.AlterField(
            model_name='statuspage',
            name='token_hash',
            field=models.CharField(db_index=True, editable=False, help_text='HMAC-SHA256 of the token; the public URL is looked up by it.', max_length=64, unique=True),
        ),
    ]
