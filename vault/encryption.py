"""
Encryption utilities using AES-GCM for vault secrets and PSA credentials.
Master key is loaded from APP_MASTER_KEY environment variable (base64-encoded 32 bytes).
"""
import base64
import contextlib
import contextvars
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


def decode_master_key(key_b64, *, label='APP_MASTER_KEY'):
    """Normalise and decode a base64 master key to its 32 raw bytes.

    Accepts standard or URL-safe base64, padded or not. Raises
    EncryptionError (never echoing the key) when it is not 32 bytes.
    """
    if isinstance(key_b64, bytes) and len(key_b64) == 32:
        return key_b64
    if not key_b64:
        raise EncryptionError(f"{label} not configured")
    if isinstance(key_b64, bytes):
        key_b64 = key_b64.decode('ascii', 'replace')
    raw_len = len(key_b64)
    key_b64 = key_b64.strip()  # Remove any whitespace/newlines

    # Normalise URL-safe base64 → standard base64.
    # Fernet.generate_key() uses urlsafe_b64encode (- and _ instead of + and /).
    # base64.b64decode silently strips those chars, producing the wrong byte count.
    key_b64 = key_b64.replace('-', '+').replace('_', '/')

    # Re-pad correctly: strip any existing = then add the right amount.
    key_b64 = key_b64.rstrip('=')
    padding = (4 - len(key_b64) % 4) % 4
    key_b64 = key_b64 + '=' * padding

    try:
        key = base64.b64decode(key_b64)
    except Exception as e:
        # Provide helpful error message without exposing the actual key
        raise EncryptionError(
            f"Invalid {label} format: {e}\n"
            f"Key length: {raw_len} characters\n"
            f"The {label} must be a valid base64-encoded 32-byte key.\n"
            f"To regenerate: python3 -c \"import base64, os; print(base64.b64encode(os.urandom(32)).decode())\""
        )

    if len(key) != 32:
        raise EncryptionError(
            f"{label} must decode to 32 bytes, got {len(key)} bytes.\n"
            f"Current key length: {raw_len} characters\n"
            f"To regenerate: python3 -c \"import base64, os; print(base64.b64encode(os.urandom(32)).decode())\""
        )

    return key


# ---------------------------------------------------------------------------
# Key selection.
#
# Normally the current key is settings.APP_MASTER_KEY and decryption also
# tries every key in settings.APP_MASTER_KEY_PREVIOUS (comma-separated), so a
# key can be rotated without downtime: deploy the new key with the old one
# listed as previous, run `manage.py rotate_encryption_key`, then drop the
# previous key.
#
# `using_master_keys()` pins the keys for a block of code. The rotation
# command uses it to decrypt with the old key and encrypt with the new one in
# the same process without touching settings.
# ---------------------------------------------------------------------------

_key_override = contextvars.ContextVar('vault_master_key_override', default=None)


@contextlib.contextmanager
def using_master_keys(encrypt_key, decrypt_keys=None):
    """Pin the master key(s) used inside the block.

    encrypt_key: base64 string or 32 raw bytes; new ciphertext uses it.
    decrypt_keys: iterable of keys tried, in order, when decrypting.
        Defaults to [encrypt_key] only — no fallback to configured keys.
    """
    enc = decode_master_key(encrypt_key, label='encryption key')
    decs = [decode_master_key(k, label='decryption key')
            for k in (decrypt_keys if decrypt_keys is not None else [encrypt_key])]
    token = _key_override.set((enc, decs))
    try:
        yield
    finally:
        _key_override.reset(token)


def get_master_key():
    """
    The key new ciphertext is written with: the pinned key inside
    `using_master_keys()`, else settings.APP_MASTER_KEY.
    Validates it's properly formatted (base64-encoded 32 bytes).
    """
    override = _key_override.get()
    if override is not None:
        return override[0]
    return decode_master_key(getattr(settings, 'APP_MASTER_KEY', ''))


def get_previous_master_keys():
    """Configured previous keys (APP_MASTER_KEY_PREVIOUS), decoded.

    Accepts a list/tuple or a comma-separated string. Invalid entries raise:
    a typo here should fail loudly at the first decrypt, not silently drop
    the key a rotation depends on.
    """
    raw = getattr(settings, 'APP_MASTER_KEY_PREVIOUS', '') or ''
    if isinstance(raw, str):
        items = [k.strip() for k in raw.split(',') if k.strip()]
    else:
        items = [k for k in raw if k]
    return [decode_master_key(k, label='APP_MASTER_KEY_PREVIOUS entry') for k in items]


def get_decryption_keys():
    """Keys to try when decrypting, current key first."""
    override = _key_override.get()
    if override is not None:
        return list(override[1])
    keys = [get_master_key()]
    for k in get_previous_master_keys():
        if k not in keys:
            keys.append(k)
    return keys


def encrypt(plaintext: str) -> str:
    """
    Encrypt plaintext using AES-GCM.
    Returns base64-encoded string in format: nonce||ciphertext
    """
    if not plaintext:
        return ""

    try:
        key = get_master_key()
        aesgcm = AESGCM(key)

        # Generate random nonce (96 bits / 12 bytes recommended for GCM)
        nonce = os.urandom(12)

        # Encrypt
        plaintext_bytes = plaintext.encode('utf-8')
        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)

        # Combine nonce + ciphertext and encode as base64
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode('ascii')

    except Exception as e:
        raise EncryptionError(f"Encryption failed: {e}")


def decrypt(encrypted: str) -> str:
    """
    Decrypt encrypted string (base64-encoded nonce||ciphertext).
    Returns plaintext string.

    v3.17.453: also handles legacy Fernet-encoded entries written by an
    older version of the encryption layer. Fernet tokens start with the
    `gAAAAA` prefix (URL-safe base64 of the 0x80 version byte) and use
    URL-safe base64 throughout, which standard `base64.b64decode` rejects
    — surfaces as a `binascii.Error: ... cannot be 1 more than a multiple
    of 4` because `_` and `-` get stripped. Detect the prefix and
    decrypt with Fernet (same 32-byte master key, just wrapped).
    """
    if not encrypted:
        return ""

    last_error = None
    try:
        keys = get_decryption_keys()
    except Exception as e:
        raise EncryptionError(f"Decryption failed: {e}")
    for key in keys:
        try:
            # Legacy Fernet path
            if isinstance(encrypted, str) and encrypted.startswith('gAAAAA'):
                fernet = Fernet(base64.urlsafe_b64encode(key))
                return fernet.decrypt(encrypted.encode('ascii')).decode('utf-8')

            # Current AES-GCM path
            aesgcm = AESGCM(key)
            combined = base64.b64decode(encrypted)
            nonce = combined[:12]
            ciphertext = combined[12:]
            plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext_bytes.decode('utf-8')
        except Exception as e:
            last_error = e
    raise EncryptionError(f"Decryption failed: {last_error!r}")


def encrypt_dict(data: dict) -> dict:
    """
    Encrypt all string values in a dictionary.
    Returns new dict with encrypted values.
    """
    encrypted = {}
    for key, value in data.items():
        if isinstance(value, str):
            encrypted[key] = encrypt(value)
        elif isinstance(value, dict):
            encrypted[key] = encrypt_dict(value)
        else:
            encrypted[key] = value
    return encrypted


def decrypt_dict(data: dict) -> dict:
    """
    Decrypt all string values in a dictionary.
    Returns new dict with decrypted values.
    """
    decrypted = {}
    for key, value in data.items():
        if isinstance(value, str):
            try:
                decrypted[key] = decrypt(value)
            except EncryptionError:
                # If decryption fails, return as-is (might not be encrypted)
                decrypted[key] = value
        elif isinstance(value, dict):
            decrypted[key] = decrypt_dict(value)
        else:
            decrypted[key] = value
    return decrypted


def get_fernet():
    """Fernet instance keyed by the normalised master key.

    `Fernet(settings.APP_MASTER_KEY.encode())` — what backup and restore used
    to do — hands Fernet the raw configured string. Fernet then base64-decodes
    it itself, so it rejects key shapes this module deliberately accepts: an
    unpadded key passes everywhere in the application and fails here. Restore
    is the worst place to discover that.

    Routing through `get_master_key()` applies the same normalisation as the
    rest of the vault. It is backward compatible by construction: both paths
    end at the same 32 raw bytes for any key the old path accepted, so
    backups written before this change still decrypt.
    """
    return Fernet(base64.urlsafe_b64encode(get_master_key()))


def get_multi_fernet():
    """MultiFernet over the current key and APP_MASTER_KEY_PREVIOUS.

    Encrypts with the current key and decrypts with any of them, so a backup
    taken before a key rotation can still be restored during the transition.
    """
    from cryptography.fernet import MultiFernet
    return MultiFernet([Fernet(base64.urlsafe_b64encode(k)) for k in get_decryption_keys()])
