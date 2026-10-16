"""Encrypt existing TOTP seeds and hash existing backup codes (v3.17.611).

See accounts/otp_storage.py. Enrolled authenticator apps keep working (the
seed is unchanged, only how it is stored), and unused backup codes keep
working (a submitted code is hashed before comparison).

Reverse decrypts the TOTP seeds back to hex. Backup-code hashes cannot be
reversed: rolling back past this migration means generating new codes.
"""
import logging

from django.db import migrations

logger = logging.getLogger('accounts')

TOTP_AAD = 'otp_totp.TOTPDevice.key'


def _table(apps, app_label, model_name, field_name):
    model = apps.get_model(app_label, model_name)
    return model, model._meta.db_table, model._meta.get_field(field_name).column


def forward(apps, schema_editor):
    from vault.secret_fields import (
        hash_static_token, is_hashed_static_token, is_sealed_hex, seal_hex,
    )
    conn = schema_editor.connection
    qn = conn.ops.quote_name

    model, table, col = _table(apps, 'otp_totp', 'TOTPDevice', 'key')
    max_len = model._meta.get_field('key').max_length
    with conn.cursor() as cur:
        cur.execute(f'SELECT id, {qn(col)} FROM {qn(table)}')
        rows = cur.fetchall()
    for pk, value in rows:
        if not value or is_sealed_hex(value):
            continue
        try:
            sealed = seal_hex(value, TOTP_AAD, max_len)
        except Exception as e:  # malformed / oversized seed: leave for check_secrets_storage
            logger.error('accounts 0036: TOTPDevice pk=%s left unencrypted: %s', pk, e)
            continue
        with conn.cursor() as cur:
            cur.execute(f'UPDATE {qn(table)} SET {qn(col)} = %s WHERE id = %s', [sealed, pk])

    _m, table, col = _table(apps, 'otp_static', 'StaticToken', 'token')
    with conn.cursor() as cur:
        cur.execute(f'SELECT id, {qn(col)} FROM {qn(table)}')
        rows = cur.fetchall()
    for pk, value in rows:
        if not value or is_hashed_static_token(value):
            continue
        with conn.cursor() as cur:
            cur.execute(f'UPDATE {qn(table)} SET {qn(col)} = %s WHERE id = %s',
                        [hash_static_token(value), pk])


def backward(apps, schema_editor):
    from vault.secret_fields import is_sealed_hex, unseal_hex
    conn = schema_editor.connection
    qn = conn.ops.quote_name
    _m, table, col = _table(apps, 'otp_totp', 'TOTPDevice', 'key')
    with conn.cursor() as cur:
        cur.execute(f'SELECT id, {qn(col)} FROM {qn(table)}')
        rows = cur.fetchall()
    for pk, value in rows:
        if is_sealed_hex(value):
            with conn.cursor() as cur:
                cur.execute(f'UPDATE {qn(table)} SET {qn(col)} = %s WHERE id = %s',
                            [unseal_hex(value, TOTP_AAD), pk])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0035_roletemplate_network_discovery_generate'),
        ('otp_totp', '0003_add_timestamps'),
        ('otp_static', '0003_add_timestamps'),
    ]

    operations = [
        migrations.RunPython(forward, backward, elidable=False),
    ]
