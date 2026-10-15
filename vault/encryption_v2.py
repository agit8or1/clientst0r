"""
Enhanced encryption utilities with best-practice security features.

Uses AES-256-GCM with:
- Key derivation (HKDF) for purpose-specific keys
- Associated Authenticated Data (AAD) for context binding
- Version tagging for key rotation support
- Memory clearing for sensitive data
- Comprehensive error handling

Master key loaded from APP_MASTER_KEY environment variable (base64-encoded 32 bytes).
"""
import base64
import os
import struct
from typing import Optional, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


# Encryption version for future key rotation
ENCRYPTION_VERSION = 2

# Key derivation contexts for different data types
KEY_CONTEXT_PASSWORD = b"password_vault_v1"
KEY_CONTEXT_API_KEY = b"api_credentials_v1"
KEY_CONTEXT_TOTP = b"totp_secrets_v1"
KEY_CONTEXT_PSA = b"psa_credentials_v1"
KEY_CONTEXT_RMM = b"rmm_credentials_v1"
KEY_CONTEXT_GENERIC = b"generic_data_v1"


def get_master_key() -> bytes:
    """
    The current 32-byte master key.

    Delegates to `vault.encryption.get_master_key` so both layers normalise
    the configured key identically (URL-safe base64, missing padding) and
    honour `using_master_keys()` during key rotation. An earlier copy here
    did not normalise URL-safe keys, so a key containing `-` or `_` worked
    for v1 and failed for v2.

    Raises:
        EncryptionError: If key is missing or invalid
    """
    from . import encryption as _v1
    try:
        return _v1.get_master_key()
    except _v1.EncryptionError as e:
        raise EncryptionError(str(e))


def _decryption_keys():
    from . import encryption as _v1
    try:
        return _v1.get_decryption_keys()
    except _v1.EncryptionError as e:
        raise EncryptionError(str(e))


def derive_key(context: bytes, master_key: Optional[bytes] = None) -> bytes:
    """
    Derive a purpose-specific key from the master key using HKDF.

    This provides:
    - Key separation: Different purposes use different keys
    - Domain separation: Prevents key reuse attacks
    - Forward secrecy: Compromise of one derived key doesn't expose others

    Args:
        context: Purpose-specific context (e.g., KEY_CONTEXT_PASSWORD)

    Returns:
        32-byte derived key
    """
    if master_key is None:
        master_key = get_master_key()

    try:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits for AES-256
            salt=None,  # Salt not needed with high-entropy master key
            info=context,  # Context binds key to specific purpose
        )
        derived_key = hkdf.derive(master_key)
        return derived_key
    finally:
        # Clear master key from memory (best effort)
        if isinstance(master_key, bytes):
            # Python doesn't guarantee memory clearing, but we try
            master_key = b'\x00' * len(master_key)


def build_aad(
    org_id: Optional[int] = None,
    record_type: Optional[str] = None,
    record_id: Optional[int] = None
) -> bytes:
    """
    Build Associated Authenticated Data (AAD) for GCM.

    AAD provides additional context that must match during decryption.
    This prevents:
    - Ciphertext reuse between organizations
    - Ciphertext reuse between record types
    - Ciphertext reuse between records

    Args:
        org_id: Organization ID
        record_type: Type of record (e.g., 'password', 'api_key')
        record_id: Record ID

    Returns:
        AAD bytes (can be empty if no context provided)
    """
    aad_parts = []

    if org_id is not None:
        aad_parts.append(f"org:{org_id}".encode('utf-8'))
    if record_type:
        aad_parts.append(f"type:{record_type}".encode('utf-8'))
    if record_id is not None:
        aad_parts.append(f"id:{record_id}".encode('utf-8'))

    return b'||'.join(aad_parts)


def encrypt_v2(
    plaintext: str,
    context: bytes = KEY_CONTEXT_GENERIC,
    org_id: Optional[int] = None,
    record_type: Optional[str] = None,
    record_id: Optional[int] = None
) -> str:
    """
    Encrypt plaintext using AES-256-GCM with enhanced security.

    Format: version(1 byte)||nonce(12 bytes)||ciphertext (base64-encoded)

    Features:
    - Key derivation via HKDF for purpose separation
    - Associated Authenticated Data (AAD) for context binding
    - Version tagging for key rotation support
    - Cryptographically secure random nonce

    Args:
        plaintext: Data to encrypt
        context: Key derivation context (purpose)
        org_id: Organization ID for AAD
        record_type: Record type for AAD
        record_id: Record ID for AAD

    Returns:
        Base64-encoded encrypted string

    Raises:
        EncryptionError: If encryption fails
        ValueError: If plaintext is None or invalid
    """
    # FIX: Raise explicit error for None instead of silent handling
    if plaintext is None:
        raise ValueError("Cannot encrypt None value - plaintext must be a string")

    if not plaintext:
        return ""  # Empty string is valid, return empty

    try:
        # Derive purpose-specific key
        key = derive_key(context)
        aesgcm = AESGCM(key)

        # Build AAD for context binding
        aad = build_aad(org_id, record_type, record_id)

        # Generate cryptographically secure random nonce (96 bits for GCM)
        nonce = os.urandom(12)

        # Encrypt with AAD
        plaintext_bytes = plaintext.encode('utf-8')
        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, aad if aad else None)

        # Pack: version + nonce + ciphertext
        version_byte = struct.pack('B', ENCRYPTION_VERSION)
        combined = version_byte + nonce + ciphertext

        # Return base64-encoded
        return base64.b64encode(combined).decode('ascii')

    except Exception as e:
        raise EncryptionError(f"Encryption failed: {e}")
    finally:
        # Clear sensitive data from memory (best effort)
        if 'key' in locals():
            key = b'\x00' * len(key)
        if 'plaintext_bytes' in locals():
            plaintext_bytes = b'\x00' * len(plaintext_bytes)


def decrypt_v2(
    encrypted: str,
    context: bytes = KEY_CONTEXT_GENERIC,
    org_id: Optional[int] = None,
    record_type: Optional[str] = None,
    record_id: Optional[int] = None
) -> str:
    """
    Decrypt encrypted string with version detection and AAD verification.

    Supports:
    - Version 2: Enhanced encryption with AAD and key derivation
    - Version 1: Legacy encryption (falls back to original decrypt)

    Args:
        encrypted: Base64-encoded encrypted string
        context: Key derivation context (must match encryption)
        org_id: Organization ID (must match encryption)
        record_type: Record type (must match encryption)
        record_id: Record ID (must match encryption)

    Returns:
        Decrypted plaintext string

    Raises:
        EncryptionError: If decryption fails or AAD doesn't match
        ValueError: If encrypted is None or invalid
    """
    import logging
    logger = logging.getLogger('vault')

    # FIX: Raise explicit error for None instead of silent handling
    if encrypted is None:
        raise ValueError("Cannot decrypt None value - encrypted must be a string")

    if not encrypted:
        return ""  # Empty string is valid, return empty

    # v3.17.453: legacy Fernet-encoded entries (signature `gAAAAA`) use
    # URL-safe base64 that standard `base64.b64decode` rejects with a
    # confusing "1 more than a multiple of 4" error. Route those straight
    # to the v1 path which now handles Fernet via cryptography.fernet.
    # 5 entries on prod were created this way (id 103-107).
    if isinstance(encrypted, str) and encrypted.startswith('gAAAAA'):
        logger.debug(f"Decryption: Fernet signature detected, using v1 path")
        from .encryption import decrypt as v1_decrypt
        try:
            return v1_decrypt(encrypted)
        except Exception as e:
            logger.error(f"Decryption: v1 (Fernet) failed: {e}")
            raise EncryptionError(f"Decryption failed: {e}")

    try:
        # Decode from base64
        try:
            combined = base64.b64decode(encrypted)
            logger.debug(f"Decryption: Successfully decoded base64, length={len(combined)}")
        except Exception as e:
            logger.error(f"Decryption: Base64 decode failed: {e}")
            raise EncryptionError(f"Invalid base64 encoding: {e}")

        # Check if this is versioned (version 2)
        if len(combined) > 13:  # min: 1 byte version + 12 byte nonce + 1 byte ciphertext
            version = struct.unpack('B', combined[:1])[0]
            logger.debug(f"Decryption: Detected version byte: {version}")

            if version == ENCRYPTION_VERSION:
                # Version 2: Enhanced encryption
                logger.debug(f"Decryption: Using v2 decryption with context={context}, org_id={org_id}, record_type={record_type}")
                nonce = combined[1:13]
                ciphertext = combined[13:]
                aad = build_aad(org_id, record_type, record_id)

                # Try the current key, then any APP_MASTER_KEY_PREVIOUS.
                for master in _decryption_keys():
                    try:
                        key = derive_key(context, master)
                        aesgcm = AESGCM(key)
                        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, aad if aad else None)
                        result = plaintext_bytes.decode('utf-8')
                        logger.debug(f"Decryption: v2 successful, plaintext length={len(result)}")
                        return result
                    except Exception:
                        continue
                # Not raised: a v1 ciphertext whose random nonce happens to
                # start with 0x02 (1 in 256) looks versioned. Before this
                # fallback those values could never be decrypted here.
                logger.debug("Decryption: v2 failed; trying v1 in case the version byte was a nonce byte")

        # Fall back to legacy v1 decryption (no version byte)
        logger.debug(f"Decryption: Falling back to v1 decryption")
        from .encryption import decrypt
        try:
            result = decrypt(encrypted)
            logger.debug(f"Decryption: v1 successful, plaintext length={len(result)}")
            return result
        except Exception as e:
            logger.error(f"Decryption: v1 decrypt failed: {e}")
            raise

    except Exception as e:
        logger.error(f"Decryption: Final error: {e}", exc_info=True)
        raise EncryptionError(f"Decryption failed: {e}")
    finally:
        # Clear sensitive data from memory
        if 'key' in locals():
            key = b'\x00' * len(key)
        if 'plaintext_bytes' in locals():
            plaintext_bytes = b'\x00' * len(plaintext_bytes)


def encrypt_password(
    plaintext: str,
    org_id: int,
    password_id: Optional[int] = None
) -> str:
    """
    Encrypt a password with password-specific context.

    Args:
        plaintext: Password to encrypt
        org_id: Organization ID
        password_id: Password record ID (if known)

    Returns:
        Base64-encoded encrypted password
    """
    return encrypt_v2(
        plaintext,
        context=KEY_CONTEXT_PASSWORD,
        org_id=org_id,
        record_type='password',
        record_id=password_id
    )


def decrypt_password(
    encrypted: str,
    org_id: int,
    password_id: Optional[int] = None
) -> str:
    """
    Decrypt a password with password-specific context.

    Args:
        encrypted: Encrypted password
        org_id: Organization ID
        password_id: Password record ID

    Returns:
        Decrypted password
    """
    return decrypt_v2(
        encrypted,
        context=KEY_CONTEXT_PASSWORD,
        org_id=org_id,
        record_type='password',
        record_id=password_id
    )


def encrypt_api_credentials(plaintext: str, org_id: int) -> str:
    """Encrypt API credentials with API-specific context."""
    return encrypt_v2(plaintext, KEY_CONTEXT_API_KEY, org_id=org_id, record_type='api_key')


def decrypt_api_credentials(encrypted: str, org_id: int) -> str:
    """Decrypt API credentials with API-specific context."""
    return decrypt_v2(encrypted, KEY_CONTEXT_API_KEY, org_id=org_id, record_type='api_key')


def encrypt_totp_secret(plaintext: str, org_id: int) -> str:
    """Encrypt TOTP secret with TOTP-specific context."""
    return encrypt_v2(plaintext, KEY_CONTEXT_TOTP, org_id=org_id, record_type='totp')


def decrypt_totp_secret(encrypted: str, org_id: int) -> str:
    """Decrypt TOTP secret with TOTP-specific context."""
    return decrypt_v2(encrypted, KEY_CONTEXT_TOTP, org_id=org_id, record_type='totp')


# Backward compatibility - import v1 functions
from .encryption import encrypt as encrypt_v1, decrypt as decrypt_v1, encrypt_dict, decrypt_dict

__all__ = [
    'encrypt_v2',
    'decrypt_v2',
    'encrypt_password',
    'decrypt_password',
    'encrypt_api_credentials',
    'decrypt_api_credentials',
    'encrypt_totp_secret',
    'decrypt_totp_secret',
    'encrypt_v1',
    'decrypt_v1',
    'encrypt_dict',
    'decrypt_dict',
    'EncryptionError',
]
