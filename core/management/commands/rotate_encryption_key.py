"""
Re-encrypt every encrypted column under a new master key.

Two ways to run it:

Zero-downtime (recommended)
    1. Generate a key:
         python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
    2. In .env set APP_MASTER_KEY=<new> and APP_MASTER_KEY_PREVIOUS=<old>,
       then reload the app. It now writes with the new key and reads both.
    3. manage.py rotate_encryption_key            (re-encrypts to APP_MASTER_KEY)
    4. Remove APP_MASTER_KEY_PREVIOUS and reload.

Offline
    manage.py rotate_encryption_key --new-key-file /root/new.key
    then set APP_MASTER_KEY to the new key and reload. Between the commit and
    the reload the running app cannot read what was re-encrypted, so stop it
    first or use the zero-downtime flow.

Everything happens in one transaction. Each value is decrypted with the old
key(s), encrypted with the target key and decrypted again with only the target
key before anything is written; any failure rolls the whole run back and the
command exits non-zero. --dry-run does the full round trip and rolls back.

Not covered: hashed tokens (keyed by API_KEY_SECRET, not the master key) and
backup archives already on disk (restore still reads them while the old key is
listed in APP_MASTER_KEY_PREVIOUS).
"""
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from vault import encryption as v1
from vault import encryption_v2 as v2
from vault import secret_fields as sf


class Command(BaseCommand):
    help = 'Re-encrypt all stored secrets under a new master key (see module docstring).'

    def add_arguments(self, parser):
        src = parser.add_mutually_exclusive_group()
        src.add_argument('--new-key', help='New base64 key. Prefer --new-key-file / '
                         'NEW_APP_MASTER_KEY: command lines are visible to other users.')
        src.add_argument('--new-key-file', help='File containing the new base64 key.')
        parser.add_argument('--old-key-file',
                            help='File with the key the data is encrypted with now. Default: '
                                 'APP_MASTER_KEY, then APP_MASTER_KEY_PREVIOUS.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Decrypt, re-encrypt and verify everything, then roll back.')

    # ------------------------------------------------------------------
    def _read_key_file(self, path):
        try:
            with open(path) as fh:
                return fh.read().strip()
        except OSError as e:
            raise CommandError(f'Cannot read key file {path}: {e.strerror}')

    def _resolve_keys(self, opts):
        new = opts.get('new_key') or None
        if opts.get('new_key_file'):
            new = self._read_key_file(opts['new_key_file'])
        if not new and os.environ.get('NEW_APP_MASTER_KEY'):
            new = os.environ['NEW_APP_MASTER_KEY'].strip()
        try:
            if opts.get('old_key_file'):
                old_keys = [v1.decode_master_key(self._read_key_file(opts['old_key_file']),
                                                 label='old key')]
            else:
                old_keys = v1.get_decryption_keys()
            target = v1.decode_master_key(new, label='new key') if new else v1.get_master_key()
        except v1.EncryptionError as e:
            raise CommandError(str(e).splitlines()[0])
        # Decrypting with the target too makes a re-run after a partial
        # deploy harmless.
        decrypt_keys = list(old_keys)
        if target not in decrypt_keys:
            decrypt_keys.append(target)
        return target, decrypt_keys, bool(new)

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        target, decrypt_keys, explicit_new = self._resolve_keys(opts)
        if not explicit_new and len(decrypt_keys) == 1:
            self.stdout.write(self.style.WARNING(
                'No new key given and no APP_MASTER_KEY_PREVIOUS set: this re-encrypts '
                'everything under the current key (fresh nonces; also upgrades any '
                'leftover legacy values).'))

        self.counts = {}
        self.failures = []
        with transaction.atomic():
            self._rotate_envelope_columns(target, decrypt_keys)
            self._rotate_hex_envelope_columns(target, decrypt_keys)
            self._rotate_v2_row_columns(target, decrypt_keys)
            if self.failures:
                transaction.set_rollback(True)
            elif opts['dry_run']:
                transaction.set_rollback(True)

        for label, (done, skipped) in sorted(self.counts.items()):
            self.stdout.write(f'  {label}: {done} re-encrypted, {skipped} empty')
        total = sum(d for d, _ in self.counts.values())
        if self.failures:
            for label, pk, err in self.failures[:50]:
                self.stderr.write(f'  FAILED {label} pk={pk}: {err}')
            raise CommandError(
                f'{len(self.failures)} value(s) could not be re-encrypted; nothing was '
                f'changed. Is the old key right (APP_MASTER_KEY / APP_MASTER_KEY_PREVIOUS '
                f'/ --old-key-file)?')
        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'Dry run: {total} value(s) would be re-encrypted; all verified. Rolled back.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Re-encrypted {total} value(s); every one verified with the new key.'))
            if explicit_new:
                self.stdout.write('Now set APP_MASTER_KEY to the new key and reload the app.')
            else:
                self.stdout.write('You can now remove APP_MASTER_KEY_PREVIOUS and reload the app.')

    # ------------------------------------------------------------------
    def _rows(self, model, *cols):
        qn = connection.ops.quote_name
        sel = ', '.join(qn(c) for c in (model._meta.pk.column,) + cols)
        with connection.cursor() as cur:
            cur.execute(f'SELECT {sel} FROM {qn(model._meta.db_table)}')
            return cur.fetchall()

    def _update(self, model, col, pk, value):
        qn = connection.ops.quote_name
        with connection.cursor() as cur:
            cur.execute(f'UPDATE {qn(model._meta.db_table)} SET {qn(col)} = %s '
                        f'WHERE {qn(model._meta.pk.column)} = %s', [value, pk])

    def _rotate_envelope_columns(self, target, decrypt_keys):
        for model, field in sf.iter_envelope_fields():
            label = f'{field.aad}'
            done = skipped = 0
            for pk, value in self._rows(model, field.column):
                if value in (None, ''):
                    skipped += 1
                    continue
                try:
                    with v1.using_master_keys(target, decrypt_keys):
                        if sf.is_sealed(value):
                            plaintext = sf.unseal(value, field.aad)
                        else:
                            # Pre-envelope value: once the old key is gone
                            # nothing could read it, so convert it now.
                            plaintext = sf.decode_legacy(value, field.legacy)
                        new_value = sf.seal(plaintext, field.aad)
                    with v1.using_master_keys(target, [target]):
                        if sf.unseal(new_value, field.aad) != plaintext:
                            raise ValueError('verification mismatch')
                except Exception as e:
                    self.failures.append((label, pk, type(e).__name__))
                    continue
                self._update(model, field.column, pk, new_value)
                done += 1
            self.counts[label] = (done, skipped)

    def _rotate_hex_envelope_columns(self, target, decrypt_keys):
        """django-otp TOTP seeds (compact enc2h$ envelope, fixed-width column)."""
        for model, field in sf.iter_hex_envelope_fields():
            label = field.aad
            done = skipped = 0
            for pk, value in self._rows(model, field.column):
                if value in (None, ''):
                    skipped += 1
                    continue
                try:
                    with v1.using_master_keys(target, decrypt_keys):
                        plaintext = (sf.unseal_hex(value, field.aad)
                                     if sf.is_sealed_hex(value) else value)
                        new_value = sf.seal_hex(plaintext, field.aad, field.max_length)
                    with v1.using_master_keys(target, [target]):
                        if sf.unseal_hex(new_value, field.aad) != plaintext:
                            raise ValueError('verification mismatch')
                except Exception as e:
                    self.failures.append((label, pk, type(e).__name__))
                    continue
                self._update(model, field.column, pk, new_value)
                done += 1
            self.counts[label] = (done, skipped)

    def _rotate_v2_row_columns(self, target, decrypt_keys):
        from django.apps import apps
        for app_label, model_name, field_name, ctx_name, aad_cols, aad_fn in sf.V2_ROW_FIELDS:
            try:
                model = apps.get_model(app_label, model_name)
            except LookupError:
                continue
            field = model._meta.get_field(field_name)
            context = getattr(v2, ctx_name)
            cols = [model._meta.get_field(c[:-3] if c.endswith('_id') else c).column for c in aad_cols]
            label = f'{app_label}.{model_name}.{field_name}'
            done = skipped = 0
            for row in self._rows(model, field.column, *cols):
                pk, value, aad_vals = row[0], row[1], row[2:]
                if value in (None, ''):
                    skipped += 1
                    continue
                aad = aad_fn(*aad_vals)
                try:
                    with v1.using_master_keys(target, decrypt_keys):
                        if field_name == 'otp_secret' and value.startswith('otpauth://'):
                            plaintext = value  # legacy plaintext import
                        else:
                            plaintext = v2.decrypt_v2(value, context=context, **aad)
                        new_value = v2.encrypt_v2(plaintext, context=context, **aad)
                    with v1.using_master_keys(target, [target]):
                        if v2.decrypt_v2(new_value, context=context, **aad) != plaintext:
                            raise ValueError('verification mismatch')
                except Exception as e:
                    self.failures.append((label, pk, type(e).__name__))
                    continue
                self._update(model, field.column, pk, new_value)
                done += 1
            self.counts[label] = (done, skipped)
