"""Share links: store only a hash of SecureNote link tokens (v3.17.611).

SecureNote.access_token -> access_token_hash (HMAC-SHA256 via
vault.secret_fields.hash_token, purpose 'core.securenote.link'). Existing
tokens are hashed in place, so links already sent keep working. Notes that
are not link-only held '' in a UNIQUE column (so a second such note could
not be saved); they now hold NULL.

Irreversible for the token values: the reverse leaves the hashes, so rolling
back past this migration means regenerating the links.
"""
from django.db import migrations, models

PURPOSE = 'core.securenote.link'


def hash_tokens(apps, schema_editor):
    from vault.secret_fields import hash_token, looks_like_token_hash
    SecureNote = apps.get_model('core', 'SecureNote')
    conn = schema_editor.connection
    qn = conn.ops.quote_name
    table = qn(SecureNote._meta.db_table)
    col = qn(SecureNote._meta.get_field('access_token_hash').column)
    issued = qn(SecureNote._meta.get_field('link_issued_at').column)
    created = qn(SecureNote._meta.get_field('created_at').column)
    pk = qn(SecureNote._meta.pk.column)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {table} SET {col} = NULL WHERE {col} = ''")
        cur.execute(f'SELECT {pk}, {col} FROM {table} WHERE {col} IS NOT NULL')
        rows = cur.fetchall()
    for row_pk, value in rows:
        if not value or looks_like_token_hash(value):
            continue
        with conn.cursor() as cur:
            cur.execute(f'UPDATE {table} SET {col} = %s WHERE {pk} = %s',
                        [hash_token(value, PURPOSE), row_pk])
    with conn.cursor() as cur:
        cur.execute(f'UPDATE {table} SET {issued} = {created} '
                    f'WHERE {col} IS NOT NULL AND {issued} IS NULL')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0075_security_policy_idle_timeout'),
    ]

    operations = [
        migrations.AddField(
            model_name='securenote',
            name='link_issued_at',
            field=models.DateTimeField(blank=True, help_text='When the current secret link was created', null=True),
        ),
        migrations.RenameField(
            model_name='securenote',
            old_name='access_token',
            new_name='access_token_hash',
        ),
        migrations.AlterField(
            model_name='securenote',
            name='access_token_hash',
            field=models.CharField(blank=True, help_text='HMAC-SHA256 of the link-only access token (the token is shown once)', max_length=64, null=True, unique=True),
        ),
        migrations.RunPython(hash_tokens, migrations.RunPython.noop, elidable=False),
    ]
