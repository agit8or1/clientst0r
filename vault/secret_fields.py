"""
Secrets at rest: one envelope format, two model fields, one token hasher.

Envelope
--------
Every secret the application must be able to read back (API keys, client
secrets, SMTP/LDAP passwords, HMAC shared secrets, integration credential
blobs) is stored as::

    enc2$<base64(version 0x02 || nonce(12) || AES-256-GCM ciphertext+tag)>

- The AES key is derived from APP_MASTER_KEY with HKDF-SHA256 under the
  context ``field_secrets_v1`` — the same construction as the v2 layer in
  ``vault.encryption_v2``, with its own purpose so a leak of one derived key
  says nothing about the others.
- The AAD is ``"<app_label>.<Model>.<field>"``. A ciphertext copied into a
  different column fails authentication instead of decrypting into the wrong
  place. (Rows are not bound individually: several of these rows are created
  before they have a primary key and some are re-parented between
  organizations by their edit forms, both of which per-row AAD would break.)
- The ``enc2$`` prefix cannot occur in base64, so "is this already
  encrypted?" is an exact test, not a heuristic. Migrations and
  ``check_secrets_storage`` rely on that.

Fields
------
``EncryptedTextField``
    Transparent: the Python attribute is the plaintext, the column holds the
    envelope. Use it for single secrets on ordinary models.

``EncryptedJSONField``
    Same, for a JSON value (e.g. webhook custom headers).

``SealedTextField``
    Not transparent: the attribute *is* the envelope. For columns whose model
    already exposes explicit ``set_*``/``get_*`` methods (integration
    credential blobs). It exists so tooling can discover the column and so
    the methods have one place to call (``field.seal()`` / ``field.unseal()``).

Tokens the application issues and only ever compares (browser-extension
bearer tokens, inbound webhook URL tokens) are never stored reversibly: see
``hash_token``.
"""
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import struct

from django import forms
from django.conf import settings
from django.db import models

logger = logging.getLogger('vault')

ENVELOPE_PREFIX = 'enc2$'
ENVELOPE_VERSION = 2
KEY_CONTEXT_FIELD = b'field_secrets_v1'

# Shown in forms instead of a stored secret.
SECRET_PLACEHOLDER = 'Stored encrypted — leave blank to keep the current value'


class SecretFieldError(Exception):
    """Raised when an envelope cannot be opened (wrong key, tampered value)."""


# ---------------------------------------------------------------------------
# Envelope primitives
# ---------------------------------------------------------------------------

def is_sealed(value) -> bool:
    return isinstance(value, str) and value.startswith(ENVELOPE_PREFIX)


def _aad_bytes(aad) -> bytes:
    if isinstance(aad, bytes):
        return aad
    return str(aad or '').encode('utf-8')


def seal(plaintext: str, aad: str) -> str:
    """Encrypt `plaintext` into an envelope bound to `aad`."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from .encryption_v2 import derive_key

    if plaintext is None:
        raise ValueError('Cannot seal None')
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    key = derive_key(KEY_CONTEXT_FIELD)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode('utf-8'), _aad_bytes(aad))
    blob = struct.pack('B', ENVELOPE_VERSION) + nonce + ct
    return ENVELOPE_PREFIX + base64.b64encode(blob).decode('ascii')


def unseal(value: str, aad: str) -> str:
    """Decrypt an envelope. Tries the current key, then APP_MASTER_KEY_PREVIOUS."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from .encryption import get_decryption_keys
    from .encryption_v2 import derive_key

    if not is_sealed(value):
        raise SecretFieldError('Value is not an encrypted envelope')
    try:
        blob = base64.b64decode(value[len(ENVELOPE_PREFIX):], validate=True)
    except (binascii.Error, ValueError) as e:
        raise SecretFieldError(f'Malformed envelope: {e}')
    if len(blob) < 1 + 12 + 16 or blob[0] != ENVELOPE_VERSION:
        raise SecretFieldError('Malformed envelope')
    nonce, ct = blob[1:13], blob[13:]
    for master in get_decryption_keys():
        try:
            pt = AESGCM(derive_key(KEY_CONTEXT_FIELD, master)).decrypt(
                nonce, ct, _aad_bytes(aad))
            return pt.decode('utf-8')
        except Exception:
            continue
    raise SecretFieldError(
        'Could not decrypt value with APP_MASTER_KEY or APP_MASTER_KEY_PREVIOUS')


# ---------------------------------------------------------------------------
# Legacy decoding — values written before this module existed.
#
# 'plain'   the column held plaintext.
# 'auto'    the column held v1 ciphertext, v2 api-credential ciphertext
#           (org_id=0), or plaintext. Mirrors the "decrypt, else assume
#           plaintext" fallback the application used at read time, so
#           converting a row never changes the value the application used.
# 'v1'      the column held v1 ciphertext; failure raises.
# 'v1_json' a JSON object whose string values are v1 ciphertexts
#           (vault.encryption.encrypt_dict). Returns the decrypted JSON text.
# 'v1_json_key:<k>'  as v1_json, returning only key <k> of the object.
# ---------------------------------------------------------------------------

def _try_v1(value):
    from .encryption import decrypt, EncryptionError
    try:
        return True, decrypt(value)
    except (EncryptionError, Exception):
        return False, None


def _try_v2_api_org0(value):
    """vault.encryption_v2.decrypt_api_credentials(value, org_id=0), quietly."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from .encryption import get_decryption_keys
    from .encryption_v2 import derive_key, build_aad, KEY_CONTEXT_API_KEY
    try:
        blob = base64.b64decode(value, validate=True)
    except Exception:
        return False, None
    if len(blob) < 1 + 12 + 16 or blob[0] != 2:
        return False, None
    aad = build_aad(0, 'api_key', None)
    for master in get_decryption_keys():
        try:
            pt = AESGCM(derive_key(KEY_CONTEXT_API_KEY, master)).decrypt(blob[1:13], blob[13:], aad)
            return True, pt.decode('utf-8')
        except Exception:
            continue
    return False, None


def decode_legacy(value: str, mode: str = 'plain') -> str:
    """Return the plaintext a pre-envelope column value stood for."""
    if value is None or value == '':
        return value
    if mode == 'plain':
        return value
    if mode == 'auto':
        ok, pt = _try_v2_api_org0(value)
        if ok:
            return pt
        ok, pt = _try_v1(value)
        if ok:
            return pt
        return value
    if mode == 'v1':
        from .encryption import decrypt
        return decrypt(value)  # raises EncryptionError when it cannot
    if mode == 'v1_json' or mode.startswith('v1_json_key:'):
        from .encryption import decrypt_dict
        data = json.loads(value)
        if not isinstance(data, dict):
            raise SecretFieldError('Legacy credential blob is not a JSON object')
        data = decrypt_dict(data)
        if mode == 'v1_json':
            return json.dumps(data)
        return data.get(mode.split(':', 1)[1], '') or ''
    raise ValueError(f'Unknown legacy mode {mode!r}')


# ---------------------------------------------------------------------------
# Forms: never echo a stored secret.
# ---------------------------------------------------------------------------

class SecretInput(forms.PasswordInput):
    """Password input that never renders the stored value."""

    def __init__(self, attrs=None):
        attrs = {'autocomplete': 'new-password', 'placeholder': SECRET_PLACEHOLDER,
                 **(attrs or {})}
        super().__init__(attrs=attrs, render_value=False)


class SecretTextarea(forms.Textarea):
    """Textarea for multi-line secrets that never renders the stored value."""

    def __init__(self, attrs=None):
        attrs = {'placeholder': SECRET_PLACEHOLDER, 'autocomplete': 'off', **(attrs or {})}
        super().__init__(attrs=attrs)

    def format_value(self, value):
        return None


class SecretFormField(forms.CharField):
    """Blank input means "keep the stored value" (see save_form_data)."""
    widget = SecretInput

    def __init__(self, *args, **kwargs):
        kwargs['required'] = False
        kwargs.setdefault('strip', True)
        super().__init__(*args, **kwargs)

    def has_changed(self, initial, data):
        return bool(data)


def _ensure_secret_widget(field):
    """Swap a value-rendering widget for its non-rendering counterpart."""
    w = field.widget
    attrs = dict(getattr(w, 'attrs', {}) or {})
    if isinstance(w, (SecretInput, SecretTextarea)):
        return field
    if isinstance(w, forms.Textarea):
        field.widget = SecretTextarea(attrs=attrs)
    else:
        attrs.pop('value', None)
        field.widget = SecretInput(attrs=attrs)
    return field


# ---------------------------------------------------------------------------
# Model fields
# ---------------------------------------------------------------------------

class _AADMixin:
    def __init__(self, *args, aad=None, legacy='plain', **kwargs):
        # `aad` pins the binding string; pass it explicitly before renaming a
        # model or field, or existing values will stop decrypting.
        self._aad_override = aad
        self.legacy = legacy
        super().__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name, *args, **kwargs):
        super().contribute_to_class(cls, name, *args, **kwargs)
        self.aad = self._aad_override or f'{cls._meta.app_label}.{cls.__name__}.{name}'

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self._aad_override:
            kwargs['aad'] = self._aad_override
        if self.legacy != 'plain':
            kwargs['legacy'] = self.legacy
        return name, path, args, kwargs

    def seal(self, plaintext):
        return seal(plaintext, self.aad)

    def unseal(self, value):
        return unseal(value, self.aad)


class EncryptedTextField(_AADMixin, models.TextField):
    """Transparent encrypted text. See module docstring."""

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        if is_sealed(value):
            try:
                return unseal(value, self.aad)
            except SecretFieldError as e:
                # Leave the ciphertext in place rather than '' — saving the
                # row back must not erase a secret we could not read.
                logger.error('Cannot decrypt %s: %s', self.aad, e)
                return value
        # Written before encryption (or before the migration ran).
        try:
            return decode_legacy(value, self.legacy)
        except Exception:
            return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == '' or is_sealed(value):
            return value
        return seal(value, self.aad)

    def value_to_string(self, obj):
        # dumpdata / serializers export ciphertext, never the secret.
        return self.get_prep_value(self.value_from_object(obj))

    def formfield(self, **kwargs):
        kwargs.setdefault('form_class', SecretFormField)
        kwargs.setdefault('widget', SecretInput)
        field = super().formfield(**kwargs)
        return _ensure_secret_widget(field)

    def save_form_data(self, instance, data):
        # An empty submission keeps the stored secret: the input is never
        # pre-filled, so empty means "not changing it", not "clear it".
        if data in (None, ''):
            return
        super().save_form_data(instance, data)


class EncryptedJSONField(EncryptedTextField):
    """Transparent encrypted JSON value (dict/list)."""

    def from_db_value(self, value, expression, connection):
        text = super().from_db_value(value, expression, connection)
        if text is None or text == '':
            return {} if text == '' else None
        if is_sealed(text):  # undecryptable — keep the envelope
            return text
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return text

    def to_python(self, value):
        if isinstance(value, str) and value and not is_sealed(value):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value

    def get_prep_value(self, value):
        if value is None:
            return None
        if is_sealed(value):
            return value
        if not isinstance(value, str):
            value = json.dumps(value, sort_keys=True)
        if value == '':
            return value
        # Not super(): TextField.get_prep_value runs to_python, which would
        # turn the JSON text back into a dict before sealing.
        return seal(value, self.aad)

    def formfield(self, **kwargs):
        # JSON is edited through a purpose-built form field on the owning
        # form (see core.webhook_forms); never round-trip it raw.
        kwargs.setdefault('widget', SecretTextarea)
        return super().formfield(**kwargs)


class SealedTextField(_AADMixin, models.TextField):
    """Column holding an envelope that the model encrypts explicitly."""

    def seal_json(self, data) -> str:
        if not data:
            return ''
        return self.seal(json.dumps(data))

    def unseal_json(self, value):
        """Envelope → dict. Pre-envelope values are decoded with `legacy`."""
        if not value:
            return {}
        if is_sealed(value):
            return json.loads(self.unseal(value))
        return json.loads(decode_legacy(value, self.legacy) or '{}')

    def unseal_text(self, value) -> str:
        if not value:
            return ''
        if is_sealed(value):
            return self.unseal(value)
        return decode_legacy(value, self.legacy) or ''


# ---------------------------------------------------------------------------
# Issued tokens: HMAC, never reversible.
# ---------------------------------------------------------------------------

def hash_token(raw: str, purpose: str) -> str:
    """HMAC-SHA256(API_KEY_SECRET, purpose || 0x00 || raw), hex.

    Same keying as api.models.hash_api_key, with a purpose prefix so a hash
    computed for one kind of token is useless as another.
    """
    key = settings.API_KEY_SECRET.encode('utf-8')
    msg = purpose.encode('utf-8') + b'\x00' + (raw or '').encode('utf-8')
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def looks_like_token_hash(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value))


# ---------------------------------------------------------------------------
# Discovery (rotation + audit tooling)
# ---------------------------------------------------------------------------

# Columns holding one-way hashes of issued tokens: (app_label, Model, field, format).
HASHED_SECRET_FIELDS = [
    ('vault', 'WebExtensionAuthToken', 'token_hash', 'hex64'),
    ('integrations', 'DistributorConnection', 'webhook_token_hash', 'hex64'),
    ('security_alerts', 'SecurityVendorConnection', 'webhook_token_hash', 'hex64'),
    ('security_alerts', 'SIEMWebhookEndpoint', 'token_hash', 'hex64'),
    ('api', 'APIKey', 'key_hash', 'hex64'),
    ('network_discovery', 'NetworkDiscoveryToken', 'token_hash', 'hex64'),
    ('network_discovery', 'DiscoverySite', 'key_hash', 'hex64'),
    ('core', 'SecureNote', 'access_password', 'django_password'),
    ('auth', 'User', 'password', 'django_password'),
]

# Columns encrypted by their model with vault.encryption_v2 and a per-row AAD
# (organization / user). (app_label, Model, field, context name, aad builder)
# The aad builder receives the row's values for the listed columns.
V2_ROW_FIELDS = [
    ('vault', 'Password', 'encrypted_password', 'KEY_CONTEXT_PASSWORD',
     ('organization_id',), lambda org: dict(org_id=org, record_type='password', record_id=None)),
    ('vault', 'Password', 'otp_secret', 'KEY_CONTEXT_TOTP',
     ('organization_id',), lambda org: dict(org_id=org, record_type='totp', record_id=None)),
    ('vault', 'PersonalVault', 'encrypted_content', 'KEY_CONTEXT_GENERIC',
     ('user_id',), lambda uid: dict(org_id=None, record_type='personal_vault', record_id=uid)),
]

# Secret-looking columns that are knowingly NOT encrypted or hashed, with the
# reason. check_secrets_storage reports these as accepted risks rather than
# failures; anything secret-named that is in none of the lists fails it.
ACCEPTED_PLAINTEXT_FIELDS = {
    ('authtoken', 'Token', 'key'):
        'Third-party (DRF) mobile API token; stored raw by DRF. Needs a hashed '
        'token model + authentication class (follow-up).',
    ('otp_totp', 'TOTPDevice', 'key'):
        'Third-party (django-otp) TOTP seed; the library reads it raw.',
    ('otp_static', 'StaticToken', 'token'):
        'Third-party (django-otp) backup codes; the library compares them raw.',
    ('core', 'SecureNote', 'access_token'):
        'Capability-link token, re-displayed to the sender (follow-up: hash + show once).',
    ('statuspage', 'StatusPage', 'token'):
        'Private status-page link token, re-displayed in settings (follow-up).',
    ('scheduling', 'SchedulerWallboard', 'token'):
        'Wallboard TV link token, re-displayed in settings (follow-up).',
    ('psa', 'Quote', 'customer_token'):
        'Customer quote-acceptance link token, re-sent in emails (follow-up).',
    ('psa', 'TicketCSATSurvey', 'token'):
        'CSAT survey link token, emailed to requesters (follow-up).',
    ('field_ops', 'MobileDevice', 'expo_push_token'):
        'Push-notification address issued by Expo; not an authentication secret.',
}

# Secret-sounding names that are not secrets.
NOT_SECRET_FIELD_NAMES = {
    'password_type', 'p256dh_key', 'credential_id', 'idempotency_key',
    'notification_key', 'ssl_expiry_notified_key', 'domain_expiry_notified_key',
    'key_prefix', 'token_prefix', 'otp_issuer', 'auth_source',
    'ticket_priority_code',
}

SECRET_NAME_RE = (
    r'(password|passwd|passphrase|secret|token|api_?key|apikey|private_key|'
    r'credential|_pat$|^pat$|bind_password|auth_key|license_key|custom_headers)'
)


def iter_envelope_fields():
    """Yield (model, field) for every EncryptedTextField / SealedTextField."""
    from django.apps import apps
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        for f in model._meta.concrete_fields:
            if isinstance(f, (EncryptedTextField, SealedTextField)):
                yield model, f


# ---------------------------------------------------------------------------
# Migration helper
# ---------------------------------------------------------------------------

def seal_existing_rows(apps, schema_editor, app_label, model_name, field_name,
                       aad=None, legacy='plain'):
    """Encrypt every non-empty, not-yet-sealed value of one column in place.

    Raw SQL on purpose: the historical model's field would transparently
    decrypt/encrypt and hide what is actually in the column. Idempotent —
    sealed values are skipped. Returns the number of rows converted.
    """
    model = apps.get_model(app_label, model_name)
    field = model._meta.get_field(field_name)
    aad = aad or f'{app_label}.{model_name}.{field_name}'
    conn = schema_editor.connection
    qn = conn.ops.quote_name
    table, col, pk = qn(model._meta.db_table), qn(field.column), qn(model._meta.pk.column)
    converted = 0
    with conn.cursor() as cur:
        cur.execute(f'SELECT {pk}, {col} FROM {table} WHERE {col} IS NOT NULL')
        rows = cur.fetchall()
    for row_pk, value in rows:
        if value in (None, '') or is_sealed(value):
            continue
        if isinstance(value, (dict, list)):  # JSON column read by a driver
            value = json.dumps(value, sort_keys=True)
        try:
            plaintext = decode_legacy(value, legacy)
        except Exception as e:
            logger.error('seal_existing_rows: %s pk=%s left unchanged: %s', aad, row_pk, e)
            continue
        if plaintext in (None, ''):
            new_value = ''
        else:
            new_value = seal(plaintext, aad)
        with conn.cursor() as cur:
            cur.execute(f'UPDATE {table} SET {col} = %s WHERE {pk} = %s', [new_value, row_pk])
        converted += 1
    return converted


def encode_legacy(plaintext: str, mode: str = 'plain') -> str:
    """Inverse of decode_legacy: the pre-envelope representation of a value.

    Used only by migration reverses, so a rollback leaves each column in the
    form the previous release reads.
    """
    if plaintext in (None, ''):
        return plaintext
    if mode == 'plain':
        return plaintext
    if mode in ('auto', 'v1'):
        from .encryption import encrypt
        return encrypt(plaintext)
    if mode == 'v2api0':
        from .encryption_v2 import encrypt_api_credentials
        return encrypt_api_credentials(plaintext, org_id=0)
    if mode == 'v1_json':
        from .encryption import encrypt_dict
        return json.dumps(encrypt_dict(json.loads(plaintext)))
    if mode.startswith('v1_json_key:'):
        from .encryption import encrypt_dict
        return json.dumps(encrypt_dict({mode.split(':', 1)[1]: plaintext}))
    raise ValueError(f'Unknown legacy mode {mode!r}')


def unseal_existing_rows(apps, schema_editor, app_label, model_name, field_name,
                         aad=None, restore='plain'):
    """Reverse of seal_existing_rows: envelope -> legacy representation."""
    model = apps.get_model(app_label, model_name)
    field = model._meta.get_field(field_name)
    aad = aad or f'{app_label}.{model_name}.{field_name}'
    conn = schema_editor.connection
    qn = conn.ops.quote_name
    table, col, pk = qn(model._meta.db_table), qn(field.column), qn(model._meta.pk.column)
    with conn.cursor() as cur:
        cur.execute(f'SELECT {pk}, {col} FROM {table} WHERE {col} IS NOT NULL')
        rows = cur.fetchall()
    for row_pk, value in rows:
        if not is_sealed(value):
            continue
        new_value = encode_legacy(unseal(value, aad), restore)
        with conn.cursor() as cur:
            cur.execute(f'UPDATE {table} SET {col} = %s WHERE {pk} = %s', [new_value, row_pk])


def seal_column_operation(app_label, model_name, field_name, legacy='plain',
                          restore=None, aad=None):
    """A RunPython operation that seals one column, reversibly.

    `legacy` says how to read existing values; `restore` (defaults to
    `legacy`, with 'auto' restored as v1) says what the reverse writes.
    """
    from django.db import migrations

    restore = restore or ('v1' if legacy == 'auto' else legacy)

    def forward(apps, schema_editor):
        seal_existing_rows(apps, schema_editor, app_label, model_name, field_name,
                           aad=aad, legacy=legacy)

    def backward(apps, schema_editor):
        unseal_existing_rows(apps, schema_editor, app_label, model_name, field_name,
                             aad=aad, restore=restore)

    return migrations.RunPython(forward, backward, elidable=False)


def hash_token_column_operation(app_label, model_name, field_name, purpose,
                                prefix_field=None):
    """A RunPython operation that replaces raw issued tokens with their HMAC.

    Existing tokens keep working: the presented token hashes to the stored
    value. Idempotent (64-hex values are already hashes; a raw
    token_urlsafe(32) is 43 characters). Not reversible — the reverse is a
    no-op, so rolling back past it means re-issuing those tokens.
    """
    from django.db import migrations

    def forward(apps, schema_editor):
        model = apps.get_model(app_label, model_name)
        conn = schema_editor.connection
        qn = conn.ops.quote_name
        table = qn(model._meta.db_table)
        col = qn(model._meta.get_field(field_name).column)
        pk = qn(model._meta.pk.column)
        pcol = qn(model._meta.get_field(prefix_field).column) if prefix_field else None
        with conn.cursor() as cur:
            cur.execute(f'SELECT {pk}, {col} FROM {table}')
            rows = cur.fetchall()
        for row_pk, value in rows:
            if not value or looks_like_token_hash(value):
                continue
            with conn.cursor() as cur:
                if pcol:
                    cur.execute(f'UPDATE {table} SET {col} = %s, {pcol} = %s WHERE {pk} = %s',
                                [hash_token(value, purpose), value[:8], row_pk])
                else:
                    cur.execute(f'UPDATE {table} SET {col} = %s WHERE {pk} = %s',
                                [hash_token(value, purpose), row_pk])

    return migrations.RunPython(forward, migrations.RunPython.noop, elidable=False)
