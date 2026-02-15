"""
Secrets Management Utilities.

Provides secure handling of API keys, credentials, and sensitive configuration.
Supports encryption, rotation, and environment-based key management.

SECURITY NOTES:
- All secrets should be stored encrypted in the database
- API keys, tokens, passwords, and credentials must NEVER be logged
- Use separate encryption keys per environment (dev/staging/prod)
- Rotate keys periodically (at least annually, or after suspected compromise)
- Store master keys in environment variables or secret managers (AWS Secrets Manager, HashiCorp Vault, etc.)
"""
import os
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.core.management.base import BaseCommand
import json
import base64

logger = logging.getLogger('core')

# Secrets that should never be logged (even in debug mode)
SENSITIVE_KEYS = [
    'password', 'secret', 'token', 'key', 'api_key', 'api_secret',
    'client_secret', 'access_token', 'refresh_token', 'private_key',
    'app_master_key', 'db_password', 'anthropic_api_key'
]


class SecretsManager:
    """
    Centralized secrets management.
    Handles encryption, decryption, rotation, and auditing of sensitive data.
    """

    def __init__(self):
        """Initialize with master key from settings."""
        self.master_key = settings.APP_MASTER_KEY
        if not self.master_key:
            raise ValueError("APP_MASTER_KEY must be set")

        # Derive encryption key from master key
        self.fernet = self._create_fernet()

    def _create_fernet(self):
        """Create Fernet cipher from master key."""
        # Derive a proper 32-byte key using PBKDF2
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'clientst0r-salt-v1',  # Static salt (OK for app-wide master key)
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.master_key.encode()))
        return Fernet(key)

    def encrypt(self, plaintext):
        """
        Encrypt plaintext string.

        Args:
            plaintext: String to encrypt

        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ''

        try:
            encrypted = self.fernet.encrypt(plaintext.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext):
        """
        Decrypt ciphertext string.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ''

        try:
            encrypted = base64.b64decode(ciphertext.encode())
            decrypted = self.fernet.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def encrypt_dict(self, data):
        """
        Encrypt all values in a dictionary.

        Args:
            data: Dictionary with string values

        Returns:
            Dictionary with encrypted values
        """
        encrypted_data = {}
        for key, value in data.items():
            if value:
                encrypted_data[key] = self.encrypt(str(value))
            else:
                encrypted_data[key] = ''
        return encrypted_data

    def decrypt_dict(self, encrypted_data):
        """
        Decrypt all values in a dictionary.

        Args:
            encrypted_data: Dictionary with encrypted string values

        Returns:
            Dictionary with decrypted values
        """
        data = {}
        for key, value in encrypted_data.items():
            if value:
                data[key] = self.decrypt(value)
            else:
                data[key] = ''
        return data


class SecretRotationPlan:
    """
    Plan and track secret rotation.

    Rotation steps:
    1. Generate new key
    2. Re-encrypt all secrets with new key
    3. Update environment variable
    4. Verify all secrets decrypt correctly
    5. Remove old key
    """

    @staticmethod
    def generate_new_master_key():
        """
        Generate a new master key for encryption.

        Returns:
            New 256-bit master key (base64 encoded)
        """
        return Fernet.generate_key().decode()

    @staticmethod
    def rotate_secrets(old_key, new_key):
        """
        Rotate all encrypted secrets from old key to new key.

        Args:
            old_key: Current master key
            new_key: New master key

        Returns:
            dict with rotation results
        """
        from integrations.models import PSAConnection, RMMConnection
        from vault.models import Password

        results = {
            'success': False,
            'rotated_count': 0,
            'failed_count': 0,
            'errors': []
        }

        # Create managers for old and new keys
        old_manager = SecretsManager()
        old_manager.master_key = old_key
        old_manager.fernet = old_manager._create_fernet()

        new_manager = SecretsManager()
        new_manager.master_key = new_key
        new_manager.fernet = new_manager._create_fernet()

        try:
            # Rotate PSA connection credentials
            for conn in PSAConnection.objects.all():
                try:
                    if conn.encrypted_credentials:
                        # Decrypt with old key
                        encrypted_dict = json.loads(conn.encrypted_credentials)
                        credentials = old_manager.decrypt_dict(encrypted_dict)

                        # Re-encrypt with new key
                        new_encrypted_dict = new_manager.encrypt_dict(credentials)
                        conn.encrypted_credentials = json.dumps(new_encrypted_dict)
                        conn.save()

                        results['rotated_count'] += 1
                except Exception as e:
                    results['errors'].append(f"PSAConnection {conn.id}: {str(e)}")
                    results['failed_count'] += 1

            # Rotate RMM connection credentials
            for conn in RMMConnection.objects.all():
                try:
                    if conn.encrypted_credentials:
                        encrypted_dict = json.loads(conn.encrypted_credentials)
                        credentials = old_manager.decrypt_dict(encrypted_dict)

                        new_encrypted_dict = new_manager.encrypt_dict(credentials)
                        conn.encrypted_credentials = json.dumps(new_encrypted_dict)
                        conn.save()

                        results['rotated_count'] += 1
                except Exception as e:
                    results['errors'].append(f"RMMConnection {conn.id}: {str(e)}")
                    results['failed_count'] += 1

            # Rotate vault passwords
            for password in Password.objects.all():
                try:
                    if password.encrypted_password:
                        # Decrypt with old key
                        plaintext = old_manager.decrypt(password.encrypted_password)

                        # Re-encrypt with new key
                        password.encrypted_password = new_manager.encrypt(plaintext)
                        password.save()

                        results['rotated_count'] += 1
                except Exception as e:
                    results['errors'].append(f"Password {password.id}: {str(e)}")
                    results['failed_count'] += 1

            results['success'] = results['failed_count'] == 0

        except Exception as e:
            logger.error(f"Secret rotation failed: {e}")
            results['errors'].append(f"Fatal error: {str(e)}")
            results['success'] = False

        return results


def sanitize_log_data(data):
    """
    Remove sensitive information from data before logging.

    Args:
        data: Dictionary or object to sanitize

    Returns:
        Sanitized copy of data with secrets redacted
    """
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            key_lower = key.lower()

            # Check if key contains sensitive term
            is_sensitive = any(term in key_lower for term in SENSITIVE_KEYS)

            if is_sensitive:
                sanitized[key] = '[REDACTED]'
            elif isinstance(value, dict):
                sanitized[key] = sanitize_log_data(value)
            elif isinstance(value, list):
                sanitized[key] = [sanitize_log_data(item) if isinstance(item, dict) else item for item in value]
            else:
                sanitized[key] = value

        return sanitized
    else:
        return data


# Environment validation
def validate_secrets_configuration():
    """
    Validate that secrets are properly configured.

    Returns:
        list of validation errors (empty if valid)
    """
    errors = []

    # Check APP_MASTER_KEY
    if not settings.APP_MASTER_KEY:
        if not settings.DEBUG:
            errors.append("APP_MASTER_KEY not set in production")
    else:
        # Validate key format
        try:
            manager = SecretsManager()
            test_encrypted = manager.encrypt("test")
            test_decrypted = manager.decrypt(test_encrypted)
            if test_decrypted != "test":
                errors.append("APP_MASTER_KEY validation failed")
        except Exception as e:
            errors.append(f"APP_MASTER_KEY error: {str(e)}")

    # Check API_KEY_SECRET
    if not settings.API_KEY_SECRET:
        if not settings.DEBUG:
            errors.append("API_KEY_SECRET not set in production")

    # Check SECRET_KEY
    if not settings.SECRET_KEY:
        errors.append("SECRET_KEY not set")
    elif settings.SECRET_KEY == 'django-insecure-dev-key-not-for-production':
        if not settings.DEBUG:
            errors.append("Using insecure dev SECRET_KEY in production")

    # Check that secrets are different
    if settings.SECRET_KEY == settings.APP_MASTER_KEY:
        errors.append("SECRET_KEY and APP_MASTER_KEY must be different")

    if settings.SECRET_KEY == settings.API_KEY_SECRET:
        errors.append("SECRET_KEY and API_KEY_SECRET must be different")

    # Check Anthropic API key
    if not settings.ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY not set (AI features disabled)")

    return errors


# Management command integration
class Command(BaseCommand):
    """
    Management command for secrets operations.

    Usage:
        python manage.py secrets validate
        python manage.py secrets generate-key
        python manage.py secrets rotate OLD_KEY NEW_KEY
    """

    help = 'Secrets management operations'

    def add_arguments(self, parser):
        parser.add_argument('action', type=str, help='Action: validate, generate-key, rotate')
        parser.add_argument('--old-key', type=str, help='Old master key (for rotation)')
        parser.add_argument('--new-key', type=str, help='New master key (for rotation)')

    def handle(self, *args, **options):
        action = options['action']

        if action == 'validate':
            self.stdout.write('Validating secrets configuration...')
            errors = validate_secrets_configuration()

            if errors:
                self.stdout.write(self.style.ERROR('Validation failed:'))
                for error in errors:
                    self.stdout.write(self.style.ERROR(f'  - {error}'))
            else:
                self.stdout.write(self.style.SUCCESS('All secrets configured correctly'))

        elif action == 'generate-key':
            new_key = SecretRotationPlan.generate_new_master_key()
            self.stdout.write(self.style.SUCCESS('New master key generated:'))
            self.stdout.write(new_key)
            self.stdout.write(self.style.WARNING('Store this key securely and update APP_MASTER_KEY environment variable'))

        elif action == 'rotate':
            old_key = options.get('old_key')
            new_key = options.get('new_key')

            if not old_key or not new_key:
                self.stdout.write(self.style.ERROR('Both --old-key and --new-key required for rotation'))
                return

            self.stdout.write('Rotating secrets...')
            results = SecretRotationPlan.rotate_secrets(old_key, new_key)

            if results['success']:
                self.stdout.write(self.style.SUCCESS(f'Rotation complete: {results["rotated_count"]} secrets updated'))
            else:
                self.stdout.write(self.style.ERROR(f'Rotation failed: {results["failed_count"]} errors'))
                for error in results['errors']:
                    self.stdout.write(self.style.ERROR(f'  - {error}'))

        else:
            self.stdout.write(self.style.ERROR(f'Unknown action: {action}'))
