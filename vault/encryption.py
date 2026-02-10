"""
Encryption utilities using AES-GCM for vault secrets and PSA credentials.
Master key is loaded from APP_MASTER_KEY environment variable (base64-encoded 32 bytes).
"""
import base64
import os
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

    # Add padding if needed for base64 decoding
    # Base64 strings must be a multiple of 4 characters
    key_b64 = key_b64.strip()  # Remove any whitespace
    padding_needed = len(key_b64) % 4
    if padding_needed:
        key_b64 += '=' * (4 - padding_needed)

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
    """
    if not encrypted:
        return ""

    try:
        key = get_master_key()
        aesgcm = AESGCM(key)

        # Decode from base64
        combined = base64.b64decode(encrypted)

        # Split nonce and ciphertext
        nonce = combined[:12]
        ciphertext = combined[12:]

        # Decrypt
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
