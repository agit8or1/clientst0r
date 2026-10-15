"""Secrets at rest for the vault app.

1. WebExtensionAuthToken.token -> token_hash (HMAC-SHA256, like api.APIKey).
   Existing tokens are hashed in place, so installed extensions keep working.
   Irreversible: the reverse is a no-op, and rolling back past this
   migration means re-pairing browser extensions.
2. Password.license_key: plaintext -> enc2$ envelope (reverse decrypts).
3. Password.encrypted_password / otp_secret and PersonalVault.encrypted_content
   still written by the v1 layer (no HKDF purpose key, no AAD) are
   re-encrypted with v2 using exactly the context the model reads them with.
   Plaintext otpauth:// secrets left by old imports are encrypted too.
   Reverse is a no-op: the previous release reads v2.
"""
import logging

import vault.secret_fields
from django.db import migrations, models
from vault.secret_fields import hash_token_column_operation, seal_column_operation

logger = logging.getLogger('vault')


def _v2_exact(value, context, org_id, record_type, record_id):
    """True if `value` is v2 ciphertext for exactly this context/AAD."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from vault.encryption import get_decryption_keys
    from vault.encryption_v2 import derive_key, build_aad
    try:
        blob = base64.b64decode(value, validate=True)
    except Exception:
        return False
    if len(blob) < 1 + 12 + 16 or blob[0] != 2:
        return False
    aad = build_aad(org_id, record_type, record_id)
    for master in get_decryption_keys():
        try:
            AESGCM(derive_key(context, master)).decrypt(blob[1:13], blob[13:], aad or None)
            return True
        except Exception:
            continue
    return False


def upgrade_v1_to_v2(apps, schema_editor):
    from vault.encryption import decrypt as v1_decrypt
    from vault.encryption_v2 import (
        encrypt_v2, KEY_CONTEXT_PASSWORD, KEY_CONTEXT_TOTP, KEY_CONTEXT_GENERIC,
    )
    conn = schema_editor.connection
    qn = conn.ops.quote_name

    def upgrade(table, pk_col, val_col, ctx_for_row):
        with conn.cursor() as cur:
            cur.execute(f'SELECT {qn(pk_col)}, {qn(val_col)}, {ctx_for_row["select"]} '
                        f'FROM {qn(table)} WHERE {qn(val_col)} IS NOT NULL')
            rows = cur.fetchall()
        changed = 0
        for row_pk, value, ctx_val in rows:
            if not value:
                continue
            context, org_id, record_type, record_id = ctx_for_row['args'](ctx_val)
            if _v2_exact(value, context, org_id, record_type, record_id):
                continue
            if ctx_for_row.get('plaintext_prefix') and value.startswith(ctx_for_row['plaintext_prefix']):
                plaintext = value
            else:
                try:
                    plaintext = v1_decrypt(value)
                except Exception as e:  # corrupt / other key: leave for an operator
                    logger.error('vault 0015: %s.%s pk=%s not upgraded: %s', table, val_col, row_pk, e)
                    continue
            new_value = encrypt_v2(plaintext, context=context, org_id=org_id,
                                   record_type=record_type, record_id=record_id)
            with conn.cursor() as cur:
                cur.execute(f'UPDATE {qn(table)} SET {qn(val_col)} = %s WHERE {qn(pk_col)} = %s',
                            [new_value, row_pk])
            changed += 1
        return changed

    Password = apps.get_model('vault', 'Password')
    PersonalVault = apps.get_model('vault', 'PersonalVault')
    pw_table = Password._meta.db_table
    org_col = Password._meta.get_field('organization').column
    upgrade(pw_table, Password._meta.pk.column, 'encrypted_password', {
        'select': qn(org_col),
        'args': lambda org: (KEY_CONTEXT_PASSWORD, org, 'password', None),
    })
    upgrade(pw_table, Password._meta.pk.column, 'otp_secret', {
        'select': qn(org_col),
        'args': lambda org: (KEY_CONTEXT_TOTP, org, 'totp', None),
        'plaintext_prefix': 'otpauth://',
    })
    user_col = PersonalVault._meta.get_field('user').column
    upgrade(PersonalVault._meta.db_table, PersonalVault._meta.pk.column, 'encrypted_content', {
        'select': qn(user_col),
        'args': lambda uid: (KEY_CONTEXT_GENERIC, None, 'personal_vault', uid),
    })


class Migration(migrations.Migration):

    dependencies = [
        ('vault', '0014_webextensionauthtoken'),
    ]

    operations = [
        migrations.RenameField(
            model_name='webextensionauthtoken',
            old_name='token',
            new_name='token_hash',
        ),
        migrations.AlterField(
            model_name='webextensionauthtoken',
            name='token_hash',
            field=models.CharField(
                db_index=True, max_length=64, unique=True,
                help_text='HMAC-SHA256 of the bearer token. The token itself is returned '
                          'to the extension once and never stored.'),
        ),
        migrations.AddField(
            model_name='webextensionauthtoken',
            name='token_prefix',
            field=models.CharField(blank=True, max_length=12,
                                   help_text='First characters of the token, for identification only.'),
        ),
        hash_token_column_operation('vault', 'WebExtensionAuthToken', 'token_hash',
                                    'vault.webextension', prefix_field='token_prefix'),
        migrations.AlterField(
            model_name='password',
            name='license_key',
            field=vault.secret_fields.EncryptedTextField(
                blank=True, help_text='Software license key (encrypted at rest)'),
        ),
        seal_column_operation('vault', 'Password', 'license_key'),
        migrations.RunPython(upgrade_v1_to_v2, migrations.RunPython.noop, elidable=False),
    ]
