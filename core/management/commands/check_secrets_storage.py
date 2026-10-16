"""
Audit how secrets are stored. Exits non-zero when any are stored unprotected.

Checks
  1. Schema: every CharField/TextField/JSONField whose name looks like a
     secret must be an EncryptedTextField / SealedTextField, a known hashed or
     per-row-v2 column, or be listed in ACCEPTED_PLAINTEXT_FIELDS with a
     reason. Works on an empty database, so it is usable in CI.
  2. Data: no non-empty value in an encrypted column lacks the enc2$ envelope,
     no hashed column holds something that is not a hash, and no per-row v2
     column holds v1 ciphertext or plaintext.

Prints table/column/primary key only — never values.

    manage.py check_secrets_storage            # exit 1 on any finding
    manage.py check_secrets_storage --strict   # accepted risks fail too
"""
import base64
import re

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, models

from vault import secret_fields as sf


class Command(BaseCommand):
    help = 'Report secrets stored in plaintext (or with a legacy layer); exit 1 if any.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help='Also fail on ACCEPTED_PLAINTEXT_FIELDS columns that hold data.')
        parser.add_argument('--schema-only', action='store_true',
                            help='Skip the data scan.')

    def handle(self, *args, **opts):
        self.problems = []
        self.accepted = []
        self._schema_check()
        if not opts['schema_only']:
            self._data_check(strict=opts['strict'])

        for line in self.accepted:
            self.stdout.write(self.style.WARNING(f'ACCEPTED  {line}'))
        for line in self.problems:
            self.stdout.write(self.style.ERROR(f'PLAINTEXT {line}'))
        if self.problems:
            self.stdout.write(self.style.ERROR(
                f'{len(self.problems)} finding(s). See vault/secret_fields.py for the '
                f'field types and manage.py migrate / rotate_encryption_key to convert data.'))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('No unprotected secrets found.'))

    # ------------------------------------------------------------------
    def _known(self):
        hashed = {(a, m, f) for a, m, f, _ in sf.HASHED_SECRET_FIELDS}
        v2rows = {(a, m, f) for a, m, f, *_ in sf.V2_ROW_FIELDS}
        return hashed, v2rows

    def _schema_check(self):
        name_re = re.compile(sf.SECRET_NAME_RE, re.I)
        hashed, v2rows = self._known()
        for model in apps.get_models():
            if model._meta.proxy or not model._meta.managed:
                continue
            for f in model._meta.concrete_fields:
                if not isinstance(f, (models.CharField, models.TextField, models.JSONField)):
                    continue
                if f.choices or f.name in sf.NOT_SECRET_FIELD_NAMES:
                    continue
                if not name_re.search(f.name):
                    continue
                key = (model._meta.app_label, model.__name__, f.name)
                if isinstance(f, (sf.EncryptedTextField, sf.SealedTextField,
                                  sf.EncryptedHexKeyField)):
                    continue
                if key in hashed or key in v2rows or key in sf.ACCEPTED_PLAINTEXT_FIELDS:
                    continue
                self.problems.append(
                    f'{".".join(key)}: secret-named column is neither encrypted, hashed '
                    f'nor in ACCEPTED_PLAINTEXT_FIELDS')

    # ------------------------------------------------------------------
    def _values(self, model, column):
        qn = connection.ops.quote_name
        with connection.cursor() as cur:
            cur.execute(f'SELECT {qn(model._meta.pk.column)}, {qn(column)} '
                        f'FROM {qn(model._meta.db_table)} WHERE {qn(column)} IS NOT NULL')
            return cur.fetchall()

    def _data_check(self, strict):
        for model, field in sf.iter_envelope_fields():
            bad = [pk for pk, v in self._values(model, field.column)
                   if v not in ('', None) and not sf.is_sealed(v)]
            if bad:
                self.problems.append(f'{field.aad}: {len(bad)} row(s) not encrypted '
                                     f'(pk {", ".join(map(str, bad[:10]))})')

        for model, field in sf.iter_hex_envelope_fields():
            bad = [pk for pk, v in self._values(model, field.column)
                   if v not in ('', None) and not sf.is_sealed_hex(v)]
            if bad:
                self.problems.append(f'{field.aad}: {len(bad)} row(s) not encrypted '
                                     f'(pk {", ".join(map(str, bad[:10]))})')

        for (app_label, model_name), reason in sorted(sf.RETIRED_SECRET_TABLES.items()):
            model = self._model(app_label, model_name)
            if model is None:
                continue
            n = model._default_manager.count()
            if n:
                self.problems.append(f'{app_label}.{model_name}: {n} row(s) — {reason}')

        for app_label, model_name, field_name, fmt in sf.HASHED_SECRET_FIELDS:
            model = self._model(app_label, model_name)
            if model is None:
                continue
            col = model._meta.get_field(field_name).column
            bad = [pk for pk, v in self._values(model, col) if v and not self._hashed(v, fmt)]
            if bad:
                self.problems.append(f'{app_label}.{model_name}.{field_name}: {len(bad)} '
                                     f'row(s) not hashed (pk {", ".join(map(str, bad[:10]))})')

        for app_label, model_name, field_name, *_ in sf.V2_ROW_FIELDS:
            model = self._model(app_label, model_name)
            if model is None:
                continue
            col = model._meta.get_field(field_name).column
            bad = [pk for pk, v in self._values(model, col) if v and not self._looks_v2(v)]
            if bad:
                self.problems.append(f'{app_label}.{model_name}.{field_name}: {len(bad)} '
                                     f'row(s) plaintext or v1 (pk {", ".join(map(str, bad[:10]))})')

        for (app_label, model_name, field_name), reason in sorted(sf.ACCEPTED_PLAINTEXT_FIELDS.items()):
            model = self._model(app_label, model_name)
            if model is None:
                continue
            try:
                col = model._meta.get_field(field_name).column
            except Exception:
                continue
            n = sum(1 for _, v in self._values(model, col) if v)
            if not n:
                continue
            line = f'{app_label}.{model_name}.{field_name}: {n} row(s) — {reason}'
            (self.problems if strict else self.accepted).append(line)

    @staticmethod
    def _model(app_label, model_name):
        try:
            return apps.get_model(app_label, model_name)
        except LookupError:
            return None

    @staticmethod
    def _hashed(value, fmt):
        if fmt == 'hex64':
            return sf.looks_like_token_hash(value)
        if fmt == 'otp_static':
            return sf.is_hashed_static_token(value)
        if fmt == 'django_password':
            from django.contrib.auth.hashers import identify_hasher, UNUSABLE_PASSWORD_PREFIX
            if value.startswith(UNUSABLE_PASSWORD_PREFIX):
                return True
            try:
                identify_hasher(value)
                return True
            except ValueError:
                return False
        return False

    @staticmethod
    def _looks_v2(value):
        try:
            blob = base64.b64decode(value, validate=True)
        except Exception:
            return False
        return len(blob) >= 1 + 12 + 16 and blob[0] == 2
