"""
Encryption utilities using AES-GCM for vault secrets and PSA credentials.
Master key is loaded from APP_MASTER_KEY environment variable (base64-encoded 32 bytes).
"""
import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


def get_master_key():
    """
    Get the master encryption key from settings.
    Validates it's properly formatted (base64-encoded 32 bytes).
    """
    key_b64 = settings.APP_MASTER_KEY
    if not key_b64:
        raise EncryptionError("APP_MASTER_KEY not configured")

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
            f"Invalid APP_MASTER_KEY format: {e}\n"
            f"Key length: {len(settings.APP_MASTER_KEY)} characters\n"
            f"The APP_MASTER_KEY must be a valid base64-encoded 32-byte key.\n"
            f"To regenerate: python3 -c \"import base64, os; print(base64.b64encode(os.urandom(32)).decode())\""
        )

    if len(key) != 32:
        raise EncryptionError(
            f"APP_MASTER_KEY must decode to 32 bytes, got {len(key)} bytes.\n"
            f"Current key length: {len(settings.APP_MASTER_KEY)} characters\n"
            f"To regenerate: python3 -c \"import base64, os; print(base64.b64encode(os.urandom(32)).decode())\""
        )

    return key


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

    try:
        key = get_master_key()

        # Legacy Fernet path
        if isinstance(encrypted, str) and encrypted.startswith('gAAAAA'):
            from cryptography.fernet import Fernet
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
        raise EncryptionError(f"Decryption failed: {e}")


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
